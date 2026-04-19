/**
 * Configuration module — validates all env vars using zod.
 * Mirrors config/settings.py from the Python codebase.
 */
import { z } from 'zod';

// ---------------------------------------------------------------------------
// Zod schema — every env var from Python settings.py
// ---------------------------------------------------------------------------

export const envSchema = z.object({
  // Database (required for Postgres; Python default was SQLite)
  DATABASE_URL: z.string().min(1, 'DATABASE_URL is required'),

  // AI — primary provider
  AI_PRIMARY_PROVIDER: z.enum(['anthropic', 'openai']).default('anthropic'),
  ANTHROPIC_API_KEY: z.string().default(''),
  ANTHROPIC_MODEL: z.string().default('claude-sonnet-4-6'),

  // AI — OpenAI-compatible (Qwen fallback)
  OPENAI_COMPATIBLE_BASE_URL: z
    .string()
    .default('https://api.openai.com/v1'),
  OPENAI_COMPATIBLE_API_KEY: z.string().default(''),
  OPENAI_COMPATIBLE_MODEL: z.string().default('gpt-4o'),

  // LinkedIn
  LINKEDIN_CLIENT_ID: z.string().default(''),
  LINKEDIN_CLIENT_SECRET: z.string().default(''),
  LINKEDIN_ACCESS_TOKEN: z.string().default(''),
  LINKEDIN_ORGANIZATION_ID: z.string().default(''),

  // Facebook / Instagram
  FACEBOOK_APP_ID: z.string().default(''),
  FACEBOOK_APP_SECRET: z.string().default(''),
  FACEBOOK_ACCESS_TOKEN: z.string().default(''),
  FACEBOOK_PAGE_ID: z.string().default(''),
  INSTAGRAM_BUSINESS_ACCOUNT_ID: z.string().default(''),

  // Web search
  TAVILY_API_KEY: z.string().default(''),

  // Dashboard auth
  DASHBOARD_PASSWORD: z.string().default(''),
  SESSION_SECRET: z
    .string()
    .min(16, 'SESSION_SECRET must be at least 16 chars')
    .default('change_this_secret_key'),

  // Cron endpoint protection
  CRON_SECRET: z.string().default(''),

  // Dashboard server
  DASHBOARD_HOST: z.string().default('127.0.0.1'),
  DASHBOARD_PORT: z.coerce.number().int().default(8001),

  // Scheduling — post times (comma-separated HH:MM)
  LINKEDIN_POST_TIMES: z.string().default('09:00,12:00,17:00'),
  FACEBOOK_POST_TIMES: z.string().default('10:00,14:00,19:00'),
  INSTAGRAM_POST_TIMES: z.string().default('08:00,13:00,18:00'),

  // Monitoring
  MONITOR_INTERVAL_MINUTES: z.coerce.number().int().default(15),
  COMPANY_NAME: z.string().default('Azienda'),
  BRAND_KEYWORDS: z.string().default(''),

  // API versions
  FACEBOOK_API_VERSION: z.string().default('v19.0'),
});

export type EnvConfig = z.infer<typeof envSchema>;

/**
 * Validator function for ConfigModule.forRoot({ validate: zodValidate }).
 * Throws a descriptive error if any required env var is missing.
 */
export function zodValidate(config: Record<string, unknown>): EnvConfig {
  const result = envSchema.safeParse(config);
  if (!result.success) {
    // zod v4 uses .issues; v3 used .errors — handle both
    const issues = (result.error as unknown as { issues?: Array<{ path: string[]; message: string }>; errors?: Array<{ path: string[]; message: string }> }).issues
      ?? (result.error as unknown as { errors?: Array<{ path: string[]; message: string }> }).errors
      ?? [];
    const messages = issues
      .map((e: { path: string[]; message: string }) => `  ${e.path.join('.')}: ${e.message}`)
      .join('\n');
    throw new Error(`Environment validation failed:\n${messages}`);
  }
  return result.data;
}
