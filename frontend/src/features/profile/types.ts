export interface GmailProfile {
  email: string;
  is_connected: boolean;
  requires_reauth?: boolean;
  name?: string;
  signature?: string;
  preferences?: string;
  bio?: string;
}
