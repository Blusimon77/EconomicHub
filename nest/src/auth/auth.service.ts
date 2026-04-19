/**
 * Authentication service.
 * Ports _make_session_token() / _verify_session_token() from dashboard/main.py:57–70.
 *
 * Token format: "<16-byte-hex-nonce>:<sha256-hmac-hex>"
 * HMAC key: SESSION_SECRET env var (was dashboard_secret_key in Python settings).
 */
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import * as crypto from 'crypto';

export const AUTH_COOKIE = 'smm_session';

@Injectable()
export class AuthService {
  constructor(private readonly config: ConfigService) {}

  /**
   * Generates a signed session token.
   * Equivalent to Python _make_session_token(secret).
   */
  makeSessionToken(): string {
    const secret = this.config.get<string>('SESSION_SECRET') ?? '';
    const nonce = crypto.randomBytes(16).toString('hex');
    const sig = crypto
      .createHmac('sha256', secret)
      .update(nonce)
      .digest('hex');
    return `${nonce}:${sig}`;
  }

  /**
   * Verifies a session token using timing-safe comparison.
   * Equivalent to Python _verify_session_token(token, secret).
   * Uses crypto.timingSafeEqual to prevent timing attacks.
   */
  verifySessionToken(token: string): boolean {
    const secret = this.config.get<string>('SESSION_SECRET') ?? '';
    if (!token || !token.includes(':')) {
      return false;
    }

    const colonIdx = token.indexOf(':');
    const nonce = token.substring(0, colonIdx);
    const sig = token.substring(colonIdx + 1);

    if (!nonce || !sig) {
      return false;
    }

    const expected = crypto
      .createHmac('sha256', secret)
      .update(nonce)
      .digest('hex');

    try {
      // timingSafeEqual requires buffers of equal length
      const sigBuf = Buffer.from(sig, 'hex');
      const expBuf = Buffer.from(expected, 'hex');
      if (sigBuf.length !== expBuf.length) {
        return false;
      }
      return crypto.timingSafeEqual(sigBuf, expBuf);
    } catch {
      return false;
    }
  }

  /**
   * Validates the provided plain password against DASHBOARD_PASSWORD.
   * Uses timingSafeEqual to prevent timing attacks on password comparison.
   */
  verifyPassword(password: string): boolean {
    const configured = this.config.get<string>('DASHBOARD_PASSWORD') ?? '';
    if (!configured) {
      // No password configured — auth is disabled; any password "matches".
      // The AuthMiddleware handles the skip-all-auth logic when empty.
      return false;
    }
    const a = Buffer.from(password);
    const b = Buffer.from(configured);
    if (a.length !== b.length) {
      return false;
    }
    return crypto.timingSafeEqual(a, b);
  }

  /**
   * Returns true if DASHBOARD_PASSWORD is configured.
   * When false, AuthMiddleware skips authentication (preserving Python behavior).
   */
  isAuthEnabled(): boolean {
    const pw = this.config.get<string>('DASHBOARD_PASSWORD') ?? '';
    return pw.length > 0;
  }
}
