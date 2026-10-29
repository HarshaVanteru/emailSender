export interface ConnectedAccount {
  id: number;
  email: string;
  is_connected: boolean;
  requires_reauth: boolean;
  mailbox_access?: boolean;
  modify_access?: boolean;
  draft_access?: boolean;
  sync_paused?: boolean;
  mail_import_complete?: boolean;
  last_synced_at?: string | null;
}
