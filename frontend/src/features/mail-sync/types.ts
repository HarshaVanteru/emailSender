export interface SyncJob {
  id: number;
  kind?: 'initial' | 'incremental' | 'reconcile';
  finished_at?: string | null;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  error_code: string | null;
}
