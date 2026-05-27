import { test, expect } from '@playwright/test';
import path from 'path';

test.describe('NusaRail Vision System - E2E Frontend Tests', () => {
  // Asumsi Next.js berjalan di localhost:3000
  const BASE_URL = 'http://localhost:3000';
  
  test('Simulasi Upload Video Lokal dan Kestabilan UI', async ({ page }) => {
    await page.goto(BASE_URL);
    
    // Assert 1: Simulasikan unggahan file video MP4
    const videoPath = path.resolve(__dirname, '../../Tester/Mobil macet di tengah rel disaat kereta mau Lewat di Kalibata Jaksel.mp4');
    
    // Klik tab "Local Video"
    await page.click('button:has-text("Local Video")');
    
    // Set file upload
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.locator('input[type="file"]').click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(videoPath);
    
    // Pastikan UI menampilkan status uploading/loading
    await expect(page.locator('text=Uploading...')).toBeVisible({ timeout: 10000 });
    
    // Assert 2: Pastikan stream MJPEG (<img>) tidak me-return 404/500
    // Tunggu sampai stream muncul dan menggantikan status Uploading
    const imgLocator = page.locator('img[alt="Video Stream"]');
    await expect(imgLocator).toBeVisible({ timeout: 20000 });
    
    // Verifikasi bahwa src valid dan image naturalWidth > 0 (tidak broken)
    const isImageOk = await imgLocator.evaluate((img: HTMLImageElement) => img.naturalWidth > 0);
    expect(isImageOk).toBeTruthy();
  });

  test('Validasi WebSocket Panel Gemini', async ({ page }) => {
    await page.goto(BASE_URL);

    // Pastikan panel terhubung
    await expect(page.locator('text=WS Connected')).toBeVisible({ timeout: 10000 });
    
    // Assert 3: Dengarkan koneksi WebSocket dan pastikan JSON di-render
    // Teks awal adalah "Mencari data..." atau "Menghubungkan ke AI..."
    const loadingTextLocator = page.locator('text=Menghubungkan ke AI...');
    
    // Teks loading ini HARUS menghilang maksimal dalam 20 detik (Gemini_Interval = 10s)
    await expect(loadingTextLocator).toBeHidden({ timeout: 25000 });
    
    // Cek bahwa panel menampilkan status "AMAN" atau "BAHAYA" (indikasi JSON masuk)
    const statusTextLocator = page.locator('.font-bold.text-sm.shadow-lg');
    const statusText = await statusTextLocator.textContent();
    
    expect(statusText).toMatch(/AMAN|BAHAYA/i);
  });
});
