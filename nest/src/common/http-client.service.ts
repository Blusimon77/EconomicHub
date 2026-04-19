/**
 * Centralised HTTP client for web scraping.
 * Ports config/http_client.py exactly — same User-Agent, same Accept-Language,
 * same Sec-Fetch-* headers, and all 26 GDPR consent cookies.
 *
 * All agents that perform scraping MUST use this service instead of
 * instantiating axios directly.
 */
import { Injectable } from '@nestjs/common';
import axios, { AxiosInstance, AxiosResponse } from 'axios';

// ---------------------------------------------------------------------------
// Base browser-simulation headers (Chrome 124 on Windows)
// Mirrors _BASE_HEADERS in config/http_client.py
// ---------------------------------------------------------------------------
const BASE_HEADERS: Record<string, string> = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
    'AppleWebKit/537.36 (KHTML, like Gecko) ' +
    'Chrome/124.0.0.0 Safari/537.36',
  Accept:
    'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
  'Accept-Encoding': 'gzip, deflate, br',
  DNT: '0',
  'Upgrade-Insecure-Requests': '1',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
  'Sec-Fetch-Site': 'none',
};

// ---------------------------------------------------------------------------
// GDPR / privacy consent cookies — 26 entries
// Mirrors _CONSENT_COOKIES in config/http_client.py exactly.
// These auto-accept cookie banners for major CMP systems used across the web.
// ---------------------------------------------------------------------------
const CONSENT_COOKIES: Record<string, string> = {
  // Cookieconsent.js (wook / orestbida)
  cookieconsent_status: 'allow',
  cookieconsent_dismissed: 'yes',

  // CookieYes / CookieLaw
  'cookieyes-consent':
    'consentid:accepted,consent:yes,action:yes,necessary:yes,functional:yes,analytics:yes,performance:yes,advertisement:yes',

  // Cookie-Script
  CookieScriptConsent:
    '{"action":"accept","categories":"[\\"necessary\\",\\"analytics\\",\\"marketing\\",\\"functional\\"]"}',

  // Complianz (WordPress)
  cmplz_consent_status: 'all',
  complianz_consent_status: 'all',

  // Iubenda
  '_iub_cs-consent':
    '{"timestamp":"2024-01-01T00:00:00.000Z","version":"1.0","purposes":{"1":true,"2":true,"3":true,"4":true,"5":true},"id":1}',

  // OneTrust (simplified)
  OptanonAlertBoxClosed: '2024-01-01T00:00:00.000Z',
  OptanonConsent:
    'isIABGlobal=false&datestamp=Mon+Jan+01+2024&version=202309.1.0&isGpcEnabled=0&landingPath=NotLandingPage&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1%2CC0004%3A1',

  // Quantcast
  addtl_consent: 'accepted',

  // WP Cookie Notice (wp-cookie-notice)
  cookie_notice_accepted: '1',
  wpl_viewed_cookie: 'yes',

  // Borlabs Cookie
  'borlabs-cookie': '{"consents":{"statistics":true,"marketing":true}}',

  // GDPR Cookie Compliance (Moove)
  moove_gdpr_popup: '{"strict":true,"thirdparty":true,"advanced":true}',

  // Drupal EU Cookie Compliance
  'cookie-agreed': '2',
  'cookie-agreed-version': '1.0.0',

  // Generic custom (very common on Italian and international sites)
  cookie_consent: '1',
  gdpr_consent: '1',
  consent: 'accepted',
  cookieAccepted: 'true',
  CookieConsent: 'true',
  cookie_policy_accepted: '1',
  privacy_accepted: '1',
  accept_cookies: '1',
  cookies_accepted: 'yes',
  eu_cookie_law_consent: '1',
};

// Build the Cookie header string once at module load time
const COOKIE_STRING = Object.entries(CONSENT_COOKIES)
  .map(([k, v]) => `${k}=${v}`)
  .join('; ');

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

@Injectable()
export class HttpClientService {
  private readonly client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      headers: {
        ...BASE_HEADERS,
        Cookie: COOKIE_STRING,
      },
      maxRedirects: 10,
      timeout: 15000,
    });
  }

  /**
   * Returns the full headers object (base headers + consent cookies).
   * Use this when you need to pass headers to a library that doesn't use
   * the axios instance directly (e.g. async with httpx in old Python code).
   */
  headers(extra?: Record<string, string>): Record<string, string> {
    const h: Record<string, string> = {
      ...BASE_HEADERS,
      Cookie: COOKIE_STRING,
    };
    if (extra) {
      Object.assign(h, extra);
    }
    return h;
  }

  /**
   * Performs a GET request with all scraping headers pre-set.
   * Mirrors scrape_get() in config/http_client.py.
   */
  async get(url: string, timeoutMs = 15000): Promise<AxiosResponse> {
    return this.client.get(url, { timeout: timeoutMs });
  }

  /**
   * Returns an axios response with responseType:'stream' for binary downloads.
   * Mirrors scrape_stream() in config/http_client.py.
   */
  async stream(url: string, timeoutMs = 15000): Promise<AxiosResponse> {
    return this.client.get(url, {
      responseType: 'stream',
      timeout: timeoutMs,
    });
  }
}
