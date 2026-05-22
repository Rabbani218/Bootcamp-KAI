export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  center_x: number;
  center_y: number;
}

export interface Detection {
  class_name: string;
  confidence: number;
  bbox: BoundingBox;
  is_stationary: boolean;
  stationary_duration_ms: number;
}

export interface AnalyzeFrameResponse {
  status: string;
  timestamp: string;
  alert_triggered: boolean;
  critical_alert_count: number;
  detections: Detection[];
  inference_time_ms: number;
  message?: string;
  geo_location?: any;
  narrative_report?: string;
}

export interface HealthCheckResponse {
  status: string;
  timestamp: string;
  model_loaded: boolean;
  tracker_ready: boolean;
}

export interface LogEntry {
  id: string;
  timestamp: Date;
  type: 'detection' | 'alert' | 'error' | 'info';
  message: string;
  detections?: Detection[];
  alertCount?: number;
}
