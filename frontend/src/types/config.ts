export interface APIConfig {
  id: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  active: boolean;
}

export interface ReviewConfig {
  terminology: {
    blacklist: string[];
  };
}
