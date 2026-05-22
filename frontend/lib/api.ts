import axios from 'axios';
import type { AnalyzeFrameResponse, HealthCheckResponse } from './types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

/**
 * Mengirim frame gambar ke backend untuk analisis
 */
export const analyzeFrame = async (
  imageBlob: Blob,
  threshold: number = 0.5
): Promise<AnalyzeFrameResponse> => {
  try {
    const formData = new FormData();
    formData.append('file', imageBlob, 'frame.jpg');
    formData.append('threshold', String(threshold));

    const response = await apiClient.post<AnalyzeFrameResponse>(
      '/api/v1/analyze-frame',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
    return response.data;
  } catch (error) {
    console.error('❌ Frame analysis error:', error);
    throw error;
  }
};

/**
 * Check kesehatan backend
 */
export const checkHealth = async (): Promise<HealthCheckResponse> => {
  try {
    const response = await apiClient.get<HealthCheckResponse>('/api/health');
    return response.data;
  } catch (error) {
    console.error('❌ Health check failed:', error);
    throw error;
  }
};

/**
 * Get tracker status dari backend
 */
export const getTrackerStatus = async () => {
  try {
    const response = await apiClient.get('/api/v1/status');
    return response.data;
  } catch (error) {
    console.error('❌ Status check failed:', error);
    throw error;
  }
};

/**
 * Reset tracker di backend
 */
export const resetTracker = async () => {
  try {
    const response = await apiClient.post('/api/v1/reset-tracker');
    return response.data;
  } catch (error) {
    console.error('❌ Reset tracker failed:', error);
    throw error;
  }
};
