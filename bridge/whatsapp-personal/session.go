package main

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	_ "github.com/lib/pq"
	qrcode "github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// bridgeStore owns whatsmeow's own device-credential store plus a small
// table this bridge maintains itself: HAIP's session_id doesn't mean
// anything to whatsmeow (which only knows JIDs), so this is what lets a
// re-pair request or a post-restart reconnect find the right device again,
// and what lets an async event handler know which HAIP callback URLs and
// secret to use long after the original /sessions request has returned.
type bridgeStore struct {
	db        *sql.DB
	container *sqlstore.Container
}

func newBridgeStore(ctx context.Context, dsn string, logger waLog.Logger) (*bridgeStore, error) {
	container, err := sqlstore.New(ctx, "postgres", dsn, logger)
	if err != nil {
		return nil, fmt.Errorf("whatsmeow sqlstore: %w", err)
	}

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("open bridge db: %w", err)
	}
	if _, err := db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS whatsapp_bridge_session_map (
			session_id TEXT PRIMARY KEY,
			jid TEXT,
			webhook_secret TEXT NOT NULL,
			message_callback_url TEXT NOT NULL,
			status_callback_url TEXT NOT NULL,
			updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
		)
	`); err != nil {
		return nil, fmt.Errorf("create bridge session map table: %w", err)
	}

	return &bridgeStore{db: db, container: container}, nil
}

type sessionRow struct {
	SessionID          string
	JID                string
	WebhookSecret      string
	MessageCallbackURL string
	StatusCallbackURL  string
}

func (s *bridgeStore) upsert(ctx context.Context, row sessionRow) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO whatsapp_bridge_session_map (session_id, jid, webhook_secret, message_callback_url, status_callback_url, updated_at)
		VALUES ($1, $2, $3, $4, $5, now())
		ON CONFLICT (session_id) DO UPDATE SET
			jid = EXCLUDED.jid,
			webhook_secret = EXCLUDED.webhook_secret,
			message_callback_url = EXCLUDED.message_callback_url,
			status_callback_url = EXCLUDED.status_callback_url,
			updated_at = now()
	`, row.SessionID, row.JID, row.WebhookSecret, row.MessageCallbackURL, row.StatusCallbackURL)
	return err
}

func (s *bridgeStore) setJID(ctx context.Context, sessionID, jid string) error {
	_, err := s.db.ExecContext(ctx, `UPDATE whatsapp_bridge_session_map SET jid = $1, updated_at = now() WHERE session_id = $2`, jid, sessionID)
	return err
}

func (s *bridgeStore) get(ctx context.Context, sessionID string) (*sessionRow, error) {
	row := s.db.QueryRowContext(ctx, `
		SELECT session_id, COALESCE(jid, ''), webhook_secret, message_callback_url, status_callback_url
		FROM whatsapp_bridge_session_map WHERE session_id = $1
	`, sessionID)
	var r sessionRow
	if err := row.Scan(&r.SessionID, &r.JID, &r.WebhookSecret, &r.MessageCallbackURL, &r.StatusCallbackURL); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	return &r, nil
}

// deviceFor resolves a whatsmeow device store for the given JID string
// (empty = brand-new device, for a fresh pairing). Matched by scanning
// GetAllDevices rather than a direct by-JID lookup, since that keeps this
// to the two Container methods this bridge is confident are stable across
// whatsmeow versions (NewDevice, GetAllDevices) rather than depending on
// an exact GetDevice(ctx, jid) signature this code was written without a
// local Go toolchain to verify against -- see main.go's package comment.
func (s *bridgeStore) deviceFor(ctx context.Context, jid string) (*store.Device, error) {
	if jid == "" {
		return s.container.NewDevice(), nil
	}
	devices, err := s.container.GetAllDevices(ctx)
	if err != nil {
		return nil, fmt.Errorf("list devices: %w", err)
	}
	for _, d := range devices {
		if d.ID != nil && d.ID.String() == jid {
			return d, nil
		}
	}
	// Stored mapping points at a JID whatsmeow no longer has credentials
	// for (e.g. manually unlinked from the phone's Linked Devices screen)
	// -- fall back to a fresh device rather than erroring, same as a
	// first-time pairing.
	return s.container.NewDevice(), nil
}

func (s *bridgeStore) all(ctx context.Context) ([]sessionRow, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT session_id, COALESCE(jid, ''), webhook_secret, message_callback_url, status_callback_url
		FROM whatsapp_bridge_session_map WHERE jid IS NOT NULL AND jid != ''
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []sessionRow
	for rows.Next() {
		var r sessionRow
		if err := rows.Scan(&r.SessionID, &r.JID, &r.WebhookSecret, &r.MessageCallbackURL, &r.StatusCallbackURL); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

// ── session manager ──────────────────────────────────────────────────────

func newSessionManager(ctx context.Context, dsn string, logger waLog.Logger) (*sessionManager, error) {
	store, err := newBridgeStore(ctx, dsn, logger)
	if err != nil {
		return nil, err
	}
	return &sessionManager{
		active:  make(map[string]*activeClient),
		backend: store,
		waLog:   logger,
	}, nil
}

// startOrResumePairing is called for a brand-new session, a re-pair after
// logout, and (indirectly, via reconnectAll) a bridge restart. Returns the
// QR code as PNG bytes -- the caller only needs it for a fresh pairing;
// on a silent reconnect of an already-paired device there is no QR to show,
// but the endpoint always returns *some* image so the caller's response
// shape stays uniform (a 1x1 blank PNG in that case is fine -- the agent's
// UI only renders it if status comes back "pending_pairing").
func (m *sessionManager) startOrResumePairing(ctx context.Context, sessionID, secret, msgCB, statusCB string) ([]byte, error) {
	if err := m.backend.upsert(ctx, sessionRow{
		SessionID: sessionID, WebhookSecret: secret,
		MessageCallbackURL: msgCB, StatusCallbackURL: statusCB,
	}); err != nil {
		return nil, fmt.Errorf("persist session row: %w", err)
	}

	m.mu.Lock()
	if existing, ok := m.active[sessionID]; ok {
		// Refresh callback details in case they rotated (a re-pair mints a
		// fresh secret every time -- see whatsapp_personal_service.py).
		existing.webhookSecret = secret
		existing.messageCallbackURL = msgCB
		existing.statusCallbackURL = statusCB
		m.mu.Unlock()
		if existing.client.IsLoggedIn() {
			return blankPNG()
		}
	} else {
		m.mu.Unlock()
	}

	row, err := m.backend.get(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	deviceStore, err := m.deviceFor(ctx, row.JID)
	if err != nil {
		return nil, err
	}

	client := whatsmeow.NewClient(deviceStore, m.waLog)
	ac := &activeClient{client: client, webhookSecret: secret, messageCallbackURL: msgCB, statusCallbackURL: statusCB}
	m.mu.Lock()
	m.active[sessionID] = ac
	m.mu.Unlock()
	m.registerHandlers(sessionID, ac)

	if client.Store.ID != nil {
		// Already paired (a restart, or a re-pair call that raced with an
		// existing connect) -- just reconnect, no QR needed.
		if err := client.Connect(); err != nil {
			return nil, fmt.Errorf("reconnect: %w", err)
		}
		return blankPNG()
	}

	qrChan, err := client.GetQRChannel(ctx)
	if err != nil {
		return nil, fmt.Errorf("get qr channel: %w", err)
	}
	if err := client.Connect(); err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}

	// WhatsApp rotates the QR roughly every 20-30s while unscanned -- a
	// real pairing attempt failed ("Couldn't link device") because this
	// used to return only the FIRST code and stop reading the channel, so
	// anyone who took longer than one rotation to actually scan it (the
	// realistic case for a first-time user finding Linked Devices) tried
	// to link an already-expired code. The first code still returns
	// synchronously so the HTTP call doesn't block, but a background
	// goroutine keeps draining the channel and pushes every later
	// rotation to HAIP over the same status webhook the frontend already
	// polls, so the displayed QR refreshes itself instead of going stale
	// with no indication.
	first, ok := <-qrChan
	if !ok {
		return nil, fmt.Errorf("qr channel closed before first code (timed out or cancelled)")
	}
	if first.Event == "success" {
		// Paired before we ever emitted a "code" event (rare -- e.g. an
		// already-scanned session from a race).
		return blankPNG()
	}
	if first.Event != "code" {
		return nil, fmt.Errorf("unexpected first qr event: %s", first.Event)
	}
	firstPNG, err := qrcode.Encode(first.Code, qrcode.Medium, 320)
	if err != nil {
		return nil, fmt.Errorf("encode qr: %w", err)
	}

	go func() {
		for evt := range qrChan {
			switch evt.Event {
			case "code":
				png, err := qrcode.Encode(evt.Code, qrcode.Medium, 320)
				if err != nil {
					fmt.Printf("session %s: qr rotation encode failed: %v\n", sessionID, err)
					continue
				}
				payload := map[string]interface{}{
					"status":            "pending_pairing",
					"qr_code_data_url": "data:image/png;base64," + base64.StdEncoding.EncodeToString(png),
				}
				postJSON(ac.statusCallbackURL, ac.webhookSecret, payload)
			case "timeout":
				// WhatsApp gave up rotating codes -- the agent needs to hit
				// Pair again for a fresh attempt rather than stare at a
				// permanently dead QR with no signal anything changed.
				postJSON(ac.statusCallbackURL, ac.webhookSecret, map[string]interface{}{"status": "logged_out"})
			}
		}
	}()

	return firstPNG, nil
}

func (m *sessionManager) deviceFor(ctx context.Context, jid string) (*store.Device, error) {
	return m.backend.deviceFor(ctx, jid)
}

func (m *sessionManager) logout(ctx context.Context, sessionID string) error {
	m.mu.Lock()
	ac, ok := m.active[sessionID]
	delete(m.active, sessionID)
	m.mu.Unlock()

	if ok {
		ac.client.Logout(ctx)
		ac.client.Disconnect()
	}
	return m.backend.setJID(ctx, sessionID, "")
}

func (m *sessionManager) reconnectAll(ctx context.Context) error {
	rows, err := m.backend.all(ctx)
	if err != nil {
		return err
	}
	for _, row := range rows {
		deviceStore, err := m.deviceFor(ctx, row.JID)
		if err != nil {
			fmt.Printf("reconnectAll: session %s: %v\n", row.SessionID, err)
			continue
		}
		client := whatsmeow.NewClient(deviceStore, m.waLog)
		ac := &activeClient{
			client: client, webhookSecret: row.WebhookSecret,
			messageCallbackURL: row.MessageCallbackURL, statusCallbackURL: row.StatusCallbackURL,
		}
		m.mu.Lock()
		m.active[row.SessionID] = ac
		m.mu.Unlock()
		m.registerHandlers(row.SessionID, ac)
		if err := client.Connect(); err != nil {
			fmt.Printf("reconnectAll: session %s connect failed: %v\n", row.SessionID, err)
		}
	}
	return nil
}

// ── event handling ───────────────────────────────────────────────────────

func (m *sessionManager) registerHandlers(sessionID string, ac *activeClient) {
	ac.client.AddEventHandler(func(rawEvt interface{}) {
		switch evt := rawEvt.(type) {
		case *events.Message:
			m.handleMessage(sessionID, ac, evt)
		case *events.PairSuccess:
			jid := evt.ID.String()
			_ = m.backend.setJID(context.Background(), sessionID, jid)
			postStatus(ac, "connected", jid, evt.ID.User)
		case *events.Connected:
			if ac.client.Store.ID != nil {
				postStatus(ac, "connected", ac.client.Store.ID.String(), ac.client.Store.ID.User)
			}
		case *events.Disconnected:
			postStatus(ac, "disconnected", "", "")
		case *events.LoggedOut:
			postStatus(ac, "logged_out", "", "")
		}
	})
}

func (m *sessionManager) handleMessage(sessionID string, ac *activeClient, evt *events.Message) {
	if evt.Info.IsFromMe || evt.Info.IsGroup {
		// Phase 1 scope: inbound 1:1 guest messages only. The agent's own
		// outgoing messages (sent from their own WhatsApp app) and group
		// chats are out of scope -- HAIP's Inbox/Leads360 model is guest
		// conversations, not arbitrary group traffic.
		return
	}

	body := evt.Message.GetConversation()
	if body == "" {
		if ext := evt.Message.GetExtendedTextMessage(); ext != nil {
			body = ext.GetText()
		}
	}
	if body == "" {
		return // media-only message with no caption -- nothing to capture yet
	}

	payload := map[string]interface{}{
		"bridge_message_id": evt.Info.ID,
		"from_phone":        "+" + evt.Info.Sender.User,
		"from_name":         evt.Info.PushName,
		"body":              body,
		"occurred_at":       evt.Info.Timestamp.UTC().Format(time.RFC3339),
	}
	postJSON(ac.messageCallbackURL, ac.webhookSecret, payload)
}

func postStatus(ac *activeClient, status, jid, phoneUser string) {
	payload := map[string]interface{}{"status": status}
	if jid != "" {
		payload["device_jid"] = jid
	}
	if phoneUser != "" {
		payload["phone_number"] = "+" + phoneUser
	}
	postJSON(ac.statusCallbackURL, ac.webhookSecret, payload)
}

func postJSON(url, secret string, payload map[string]interface{}) {
	if url == "" {
		return
	}
	body, err := json.Marshal(payload)
	if err != nil {
		fmt.Printf("postJSON marshal: %v\n", err)
		return
	}
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		fmt.Printf("postJSON request: %v\n", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Bridge-Secret", secret)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		fmt.Printf("postJSON to %s failed: %v\n", url, err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		fmt.Printf("postJSON to %s returned %d\n", url, resp.StatusCode)
	}
}

func blankPNG() ([]byte, error) {
	return qrcode.Encode(" ", qrcode.Low, 1)
}
