export interface BrowserRequest {
  id: number;
  method: 'fetch_page_text' | 'fetch_page_html' | 'shutdown';
  params?: {
    url: string;
    timeout?: number;
  };
}

export interface BrowserResponse {
  id: number;
  result?: string;
  error?: string;
}
