# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests\e2e\playwright_e2e.spec.ts >> NusaRail Vision System - E2E Frontend Tests >> Validasi WebSocket Panel Gemini
- Location: tests\e2e\playwright_e2e.spec.ts:36:7

# Error details

```
Error: expect(received).toMatch(expected)

Expected pattern: /AMAN|BAHAYA/i
Received string:  "MENGINISIALISASI"
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - main [ref=e2]:
    - generic [ref=e3]:
      - generic [ref=e4]:
        - generic [ref=e5]:
          - heading "NusaRail Sentinel" [level=1] [ref=e6]:
            - img [ref=e7]
            - generic [ref=e9]: NusaRail Sentinel
          - paragraph [ref=e10]: Enterprise-Grade Early Warning System (Phase 4 Tactical Control)
        - generic [ref=e11]:
          - generic [ref=e16]: "DJKA Webhook: Connected"
          - generic [ref=e21]: "MQTT Signaling: Offline"
      - generic [ref=e22]:
        - button "Live Monitoring" [ref=e23] [cursor=pointer]:
          - img [ref=e24]
          - text: Live Monitoring
        - button "Analytics & Logs" [ref=e27] [cursor=pointer]:
          - img [ref=e28]
          - text: Analytics & Logs
        - button "Advanced Settings" [ref=e30] [cursor=pointer]:
          - img [ref=e31]
          - text: Advanced Settings
      - generic [ref=e34]:
        - generic [ref=e35]:
          - generic [ref=e36]:
            - button "YouTube Live" [ref=e37] [cursor=pointer]:
              - img [ref=e38]
              - text: YouTube Live
            - button "RTSP CCTV" [ref=e41] [cursor=pointer]:
              - img [ref=e42]
              - text: RTSP CCTV
            - button "Local Video" [ref=e48] [cursor=pointer]:
              - img [ref=e49]
              - text: Local Video
          - generic [ref=e52]:
            - textbox "https://www.youtube.com/watch?v=..." [ref=e53]: https://www.youtube.com/watch?v=q7lvnYVuqNY
            - button "Stream YouTube" [ref=e54] [cursor=pointer]
        - generic [ref=e55]:
          - generic [ref=e58]:
            - img "Live Stream" [ref=e59]
            - generic [ref=e60]: LIVE
          - generic [ref=e63]:
            - generic [ref=e64]:
              - heading "AI Analytics Engine" [level=2] [ref=e65]:
                - img [ref=e66]
                - text: AI Analytics Engine
              - generic [ref=e68]: WS Connected
            - generic [ref=e69]:
              - generic [ref=e70]:
                - heading "Kondisi Perlintasan" [level=3] [ref=e71]
                - generic [ref=e72]:
                  - img [ref=e73]
                  - text: MENGINISIALISASI
              - generic [ref=e75]:
                - heading "Geo-Location (AI Inference)" [level=3] [ref=e76]
                - generic [ref=e77]:
                  - img [ref=e78]
                  - generic [ref=e81]: Mencari data...
              - generic [ref=e82]:
                - heading "Insight Narasi (Gemini 2.0 Flash)" [level=3] [ref=e83]
                - generic [ref=e84]: Gemini API rate limit. Coba lagi dalam 20s.
              - generic [ref=e85]:
                - generic [ref=e86]: Live
                - generic [ref=e88]: "Update: 13.27.12"
  - alert [ref=e89]
```