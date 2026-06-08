# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests\e2e\playwright_e2e.spec.ts >> NusaRail Vision System - E2E Frontend Tests >> Simulasi Upload Video Lokal dan Kestabilan UI
- Location: tests\e2e\playwright_e2e.spec.ts:8:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('img[alt="Video Stream"]')
Expected: visible
Timeout: 20000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 20000ms
  - waiting for locator('img[alt="Video Stream"]')

```

```yaml
- main:
  - heading "NusaRail Sentinel" [level=1]:
    - img
    - text: NusaRail Sentinel
  - paragraph: Enterprise-Grade Early Warning System (Phase 4 Tactical Control)
  - text: "DJKA Webhook: Connected MQTT Signaling: Offline"
  - button "Live Monitoring":
    - img
    - text: Live Monitoring
  - button "Analytics & Logs":
    - img
    - text: Analytics & Logs
  - button "Advanced Settings":
    - img
    - text: Advanced Settings
  - button "YouTube Live":
    - img
    - text: YouTube Live
  - button "RTSP CCTV":
    - img
    - text: RTSP CCTV
  - button "Local Video":
    - img
    - text: Local Video
  - button "Choose File"
  - img "Live Stream"
  - text: LIVE
  - heading "AI Analytics Engine" [level=2]:
    - img
    - text: AI Analytics Engine
  - text: WS Connected
  - heading "Kondisi Perlintasan" [level=3]
  - img
  - text: MENGINISIALISASI
  - heading "Geo-Location (AI Inference)" [level=3]
  - img
  - text: Mencari data...
  - heading "Insight Narasi (Gemini 2.0 Flash)" [level=3]
  - text: "Gemini API rate limit. Coba lagi dalam 10s. Live Update: 13.26.52"
- alert
```