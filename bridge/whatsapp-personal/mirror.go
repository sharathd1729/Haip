package main

// WhatsApp-Web-style mirror: everything the paired phone sees (guest messages, the agent's own replies, groups, photos / videos /
// voice notes / documents, and the recent history WhatsApp hands over when a device is linked) is forwarded to HAIP.
//
// The bridge stays READ-ONLY: it never sends anything. Files are downloaded here and posted to HAIP, which stores them in object
// storage (Cloudflare R2); the bridge keeps nothing on disk. Everything for one session runs through one ordered queue so messages
// reach HAIP in the order they arrived and a slow file download never blocks WhatsApp's own event loop.

import (
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

const (
	defaultMediaMaxMB     = 16 // larger files are skipped and shown as a placeholder
	defaultHistoryDays    = 30 // history older than this is not imported
	defaultHistoryPerChat = 200
	historyBatchSize      = 100
	queueSize             = 512
)

func envInt(name string, def int) int {
	if v, err := strconv.Atoi(strings.TrimSpace(os.Getenv(name))); err == nil && v > 0 {
		return v
	}
	return def
}

// chatMessage is the JSON HAIP's /webhooks/whatsapp-personal/{session}/message (and /history) endpoints accept.
type chatMessage struct {
	BridgeMessageID string `json:"bridge_message_id"`
	FromPhone       string `json:"from_phone"`
	FromName        string `json:"from_name,omitempty"`
	Body            string `json:"body"`
	OccurredAt      string `json:"occurred_at"`
	ChatJID         string `json:"chat_jid"`
	ChatType        string `json:"chat_type"`
	ChatName        string `json:"chat_name,omitempty"`
	Direction       string `json:"direction"`
	History         bool   `json:"history,omitempty"`
	MediaKind       string `json:"media_kind,omitempty"`
	MediaMime       string `json:"media_mime,omitempty"`
	MediaFilename   string `json:"media_filename,omitempty"`
	MediaBase64     string `json:"media_base64,omitempty"`
	MediaSkipped    string `json:"media_skipped,omitempty"`
}

type mediaPart struct {
	kind, mime, filename string
	size                 uint64
	dl                   whatsmeow.DownloadableMessage
}

// extractContent returns the text (or caption) of a message and its attached file, if any. A message with neither (a reaction,
// a deleted-message notice, a poll update ...) returns ("", nil) and is not forwarded.
func extractContent(msg *waE2E.Message) (string, *mediaPart) {
	if msg == nil {
		return "", nil
	}
	if c := msg.GetConversation(); c != "" {
		return c, nil
	}
	if ext := msg.GetExtendedTextMessage(); ext != nil && ext.GetText() != "" {
		return ext.GetText(), nil
	}
	if im := msg.GetImageMessage(); im != nil {
		return im.GetCaption(), &mediaPart{"image", im.GetMimetype(), "", im.GetFileLength(), im}
	}
	if v := msg.GetVideoMessage(); v != nil {
		return v.GetCaption(), &mediaPart{"video", v.GetMimetype(), "", v.GetFileLength(), v}
	}
	if a := msg.GetAudioMessage(); a != nil {
		return "", &mediaPart{"audio", a.GetMimetype(), "", a.GetFileLength(), a}
	}
	if d := msg.GetDocumentMessage(); d != nil {
		name := d.GetFileName()
		if name == "" {
			name = d.GetTitle()
		}
		return d.GetCaption(), &mediaPart{"document", d.GetMimetype(), name, d.GetFileLength(), d}
	}
	if st := msg.GetStickerMessage(); st != nil {
		return "", &mediaPart{"sticker", st.GetMimetype(), "", st.GetFileLength(), st}
	}
	return "", nil
}

// jidPhone is the phone-number digits of a JID, or "" when it is not a phone-number JID (a @lid or @g.us id is NOT a number).
func jidPhone(j types.JID) string {
	if j.Server == types.DefaultUserServer {
		return j.User
	}
	return ""
}

func firstPhone(js ...types.JID) string {
	for _, j := range js {
		if p := jidPhone(j); p != "" {
			return "+" + p
		}
	}
	return ""
}

// phoneOf is the "+digits" phone number for the first JID that has one. A @lid ("hidden") id is not a number, but WhatsApp
// also tells the phone which number it belongs to, and the library keeps that lookup: use it before giving up.
func (ac *activeClient) phoneOf(js ...types.JID) string {
	if p := firstPhone(js...); p != "" {
		return p
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for _, j := range js {
		if j.Server != types.HiddenUserServer || ac.client.Store == nil || ac.client.Store.LIDs == nil {
			continue
		}
		if pn, err := ac.client.Store.LIDs.GetPNForLID(ctx, j); err == nil && pn.User != "" {
			return "+" + pn.User
		}
	}
	return ""
}

// contactName is the name the phone has for this person (saved contact name, else their WhatsApp name, else business name).
func (ac *activeClient) contactName(j types.JID) string {
	if ac.client.Store == nil || ac.client.Store.Contacts == nil {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	info, err := ac.client.Store.Contacts.GetContact(ctx, j)
	if err != nil {
		return ""
	}
	for _, n := range []string{info.FullName, info.PushName, info.BusinessName, info.FirstName} {
		if n != "" {
			return n
		}
	}
	return ""
}

// skippableChat: status updates, broadcast lists and channels are not conversations.
func skippableChat(j types.JID) bool {
	return j.Server == types.BroadcastServer || j.Server == types.NewsletterServer || j.User == "status"
}

func (ac *activeClient) groupName(jid types.JID) string {
	key := jid.String()
	if v, ok := ac.names.Load(key); ok {
		return v.(string)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	info, err := ac.client.GetGroupInfo(ctx, jid)
	name := ""
	if err == nil && info != nil {
		name = info.Name
	}
	if name != "" {
		ac.names.Store(key, name)
	}
	return name
}

// buildChatMessage turns one WhatsApp message into the payload HAIP expects; ok=false means "not worth forwarding".
// withMedia=false (history) never downloads files: the message carries only a kind, and HAIP shows a placeholder.
func (m *sessionManager) buildChatMessage(ac *activeClient, evt *events.Message, history bool, withMedia bool, chatName string, pnHint string) (chatMessage, bool) {
	info := evt.Info
	if skippableChat(info.Chat) {
		return chatMessage{}, false
	}
	text, media := extractContent(evt.Message)
	if text == "" && media == nil {
		return chatMessage{}, false
	}

	out := chatMessage{
		BridgeMessageID: info.ID,
		Body:            text,
		OccurredAt:      info.Timestamp.UTC().Format(time.RFC3339),
		ChatJID:         info.Chat.String(),
		ChatType:        "user",
		Direction:       "inbound",
		History:         history,
	}
	if info.IsFromMe {
		out.Direction = "outbound"
	}
	if info.IsGroup {
		out.ChatType = "group"
		out.ChatName = chatName
		if out.ChatName == "" && !history {
			out.ChatName = ac.groupName(info.Chat)
		}
		out.FromPhone = ac.phoneOf(info.Sender, info.SenderAlt)
		out.FromName = info.PushName
		if out.FromName == "" {
			out.FromName = ac.contactName(info.Sender)
		}
	} else if info.IsFromMe {
		out.FromPhone = ac.phoneOf(info.Chat, info.RecipientAlt) // the OTHER person
		out.ChatName = chatName
		if out.ChatName == "" {
			out.ChatName = ac.contactName(info.Chat)
		}
	} else {
		out.FromPhone = ac.phoneOf(info.Sender, info.SenderAlt, info.Chat)
		out.FromName = info.PushName
		if out.FromName == "" {
			out.FromName = ac.contactName(info.Sender)
		}
		out.ChatName = chatName
	}
	if out.FromPhone == "" && pnHint != "" && !info.IsGroup {
		out.FromPhone = pnHint // history gives the chat's phone-number id next to its hidden id
	}

	if media != nil {
		out.MediaKind = media.kind
		out.MediaMime = media.mime
		out.MediaFilename = media.filename
		maxBytes := uint64(envInt("MEDIA_MAX_MB", defaultMediaMaxMB)) << 20
		switch {
		case !withMedia:
			out.MediaSkipped = "history"
		case media.size > maxBytes:
			out.MediaSkipped = "too_large"
		default:
			ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
			data, err := ac.client.Download(ctx, media.dl)
			cancel()
			if err != nil || len(data) == 0 {
				fmt.Printf("[mirror] session download failed (%s): %v\n", media.kind, err)
				out.MediaSkipped = "download_failed"
			} else if uint64(len(data)) > maxBytes {
				out.MediaSkipped = "too_large"
			} else {
				out.MediaBase64 = base64.StdEncoding.EncodeToString(data)
			}
		}
	}
	return out, true
}

// handleMessage forwards one live message (guest, the agent's own, or group), in arrival order.
func (m *sessionManager) handleMessage(sessionID string, ac *activeClient, evt *events.Message) {
	msg, ok := m.buildChatMessage(ac, evt, false, true, "", "")
	if !ok {
		return
	}
	postJSON(ac.messageCallbackURL, ac.webhookSecret, msg)
}

// handleHistory forwards the recent part of the history WhatsApp sends right after linking: the newest N messages per chat from
// the last few days, text only. Older chats and files are not imported (a real WhatsApp Web has the same recent-history window).
func (m *sessionManager) handleHistory(sessionID string, ac *activeClient, evt *events.HistorySync) {
	data := evt.Data
	if data == nil {
		return
	}
	cutoff := time.Now().Add(-time.Duration(envInt("HISTORY_DAYS", defaultHistoryDays)) * 24 * time.Hour)
	perChat := envInt("HISTORY_MAX_PER_CHAT", defaultHistoryPerChat)
	historyURL := strings.TrimSuffix(ac.statusCallbackURL, "/status") + "/history"

	var batch []chatMessage
	flush := func() {
		if len(batch) == 0 {
			return
		}
		postJSON(historyURL, ac.webhookSecret, map[string]interface{}{"messages": batch})
		batch = batch[:0]
	}
	total := 0
	for _, conv := range data.GetConversations() {
		chatJID, err := types.ParseJID(conv.GetID())
		if err != nil || skippableChat(chatJID) {
			continue
		}
		name := conv.GetDisplayName()
		if name == "" {
			name = conv.GetName()
		}
		pnHint := ""
		if pn, err := types.ParseJID(conv.GetPnJID()); err == nil {
			pnHint = firstPhone(pn)
		}
		var parsed []*events.Message
		for _, hm := range conv.GetMessages() {
			wm := hm.GetMessage()
			if wm == nil {
				continue
			}
			pe, err := ac.client.ParseWebMessage(chatJID, wm)
			if err != nil || pe == nil || pe.Info.Timestamp.Before(cutoff) {
				continue
			}
			parsed = append(parsed, pe)
		}
		sort.Slice(parsed, func(i, j int) bool { return parsed[i].Info.Timestamp.After(parsed[j].Info.Timestamp) })
		if len(parsed) > perChat {
			parsed = parsed[:perChat]
		}
		for _, pe := range parsed {
			if cm, ok := m.buildChatMessage(ac, pe, true, false, name, pnHint); ok {
				batch = append(batch, cm)
				total++
				if len(batch) >= historyBatchSize {
					flush()
				}
			}
		}
	}
	flush()
	fmt.Printf("[diag] session %s: history sync forwarded %d messages (type %s)\n", sessionID, total, data.GetSyncType().String())
}

// enqueue runs fn on the session's ordered worker. If the queue is full (a huge burst) the work is dropped and logged rather than
// blocking WhatsApp's event loop.
func (ac *activeClient) enqueue(sessionID string, fn func()) {
	ac.once.Do(func() {
		ac.queue = make(chan func(), queueSize)
		go func() {
			for job := range ac.queue {
				func() {
					defer func() {
						if r := recover(); r != nil {
							fmt.Printf("[mirror] session %s: job panicked: %v\n", sessionID, r)
						}
					}()
					job()
				}()
			}
		}()
	})
	select {
	case ac.queue <- fn:
	default:
		fmt.Printf("[mirror] session %s: queue full, dropped one job\n", sessionID)
	}
}
