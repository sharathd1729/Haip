// HAIP personal WhatsApp bridge -- Phase 1 (read-only capture).
//
// Pairs an agent's own personal WhatsApp / WhatsApp Business app via QR
// code, using whatsmeow's unofficial multi-device protocol implementation
// (NOT Meta's sanctioned Business Cloud API -- see CLAUDE.md's WhatsApp
// integration notes on ban risk). Forwards inbound messages and connection
// status changes to HAIP's backend over a per-session shared secret.
//
// One process serves every paired agent across every tenant: each session
// is keyed by HAIP's own session_id (not by phone number), and whatsmeow
// device credentials persist in Postgres so a bridge restart never forces
// a guest-visible re-scan.
package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func main() {
	// Self-check mode for Docker's HEALTHCHECK -- the runtime image is
	// distroless (no shell, no wget/curl), so the healthcheck re-invokes
	// this same static binary instead of a separate tool that doesn't
	// exist in that image.
	if len(os.Args) > 1 && os.Args[1] == "--healthcheck" {
		port := os.Getenv("HTTP_PORT")
		if port == "" {
			port = "8085"
		}
		client := http.Client{Timeout: 3 * time.Second}
		resp, err := client.Get("http://localhost:" + port + "/healthz")
		if err != nil || resp.StatusCode != http.StatusOK {
			os.Exit(1)
		}
		os.Exit(0)
	}

	dsn := os.Getenv("BRIDGE_DB_DSN")
	if dsn == "" {
		log.Fatal("BRIDGE_DB_DSN is required (Postgres DSN -- whatsmeow's own device store + our session_id map live here)")
	}
	port := os.Getenv("HTTP_PORT")
	if port == "" {
		port = "8085"
	}

	waLogger := waLog.Stdout("whatsmeow", "INFO", true)
	mgr, err := newSessionManager(context.Background(), dsn, waLogger)
	if err != nil {
		log.Fatalf("session manager init failed: %v", err)
	}

	// Reconnect every previously-paired session on startup -- a bridge
	// restart (deploy, crash, host reboot) must not silently stop
	// forwarding an agent's messages until someone notices and re-pairs.
	if err := mgr.reconnectAll(context.Background()); err != nil {
		log.Printf("reconnectAll: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /sessions", mgr.handleStartSession)
	mux.HandleFunc("DELETE /sessions/{id}", mgr.handleDeleteSession)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	log.Printf("whatsapp-personal bridge listening on :%s", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

// ── HTTP handlers ────────────────────────────────────────────────────────

type startSessionRequest struct {
	SessionID          string `json:"session_id"`
	WebhookSecret      string `json:"webhook_secret"`
	MessageCallbackURL string `json:"message_callback_url"`
	StatusCallbackURL  string `json:"status_callback_url"`
	// Optional -- when set, pairing uses WhatsApp's phone-number-entry
	// code flow instead of a QR scan. Digits with or without a leading
	// "+", country code included.
	PhoneNumber string `json:"phone_number,omitempty"`
}

type startSessionResponse struct {
	QRCodeDataURL string `json:"qr_code_data_url,omitempty"`
	PairingCode   string `json:"pairing_code,omitempty"`
}

func (m *sessionManager) handleStartSession(w http.ResponseWriter, r *http.Request) {
	var req startSessionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.SessionID == "" {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}

	qrPNG, pairingCode, err := m.startOrResumePairing(r.Context(), req.SessionID, req.WebhookSecret, req.MessageCallbackURL, req.StatusCallbackURL, req.PhoneNumber)
	if err != nil {
		log.Printf("session %s: start pairing failed: %v", req.SessionID, err)
		http.Error(w, "could not start pairing", http.StatusBadGateway)
		return
	}

	resp := startSessionResponse{PairingCode: pairingCode}
	if len(qrPNG) > 0 {
		resp.QRCodeDataURL = "data:image/png;base64," + base64.StdEncoding.EncodeToString(qrPNG)
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func (m *sessionManager) handleDeleteSession(w http.ResponseWriter, r *http.Request) {
	sessionID := r.PathValue("id")
	if sessionID == "" {
		http.Error(w, "missing session id", http.StatusBadRequest)
		return
	}
	if err := m.logout(r.Context(), sessionID); err != nil {
		log.Printf("session %s: logout failed: %v", sessionID, err)
	}
	w.WriteHeader(http.StatusOK)
}

// activeClient bundles a live whatsmeow client with the HAIP callback
// details it needs whenever an event handler fires later, asynchronously.
type activeClient struct {
	client             *whatsmeow.Client
	webhookSecret      string
	messageCallbackURL string
	statusCallbackURL  string
}

type sessionManager struct {
	mu      sync.Mutex
	active  map[string]*activeClient // keyed by HAIP session_id
	backend *bridgeStore
	waLog   waLog.Logger
}
