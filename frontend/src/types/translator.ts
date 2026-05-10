export interface TranslateResult {
  text: string;
  engine: string;
}

export interface TranslateEngine {
  name: string;
  translate(text: string, source: string, target: string): Promise<TranslateResult>;
  supports(source: string, target: string): boolean;
}
