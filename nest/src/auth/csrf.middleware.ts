/**
 * CSRF double-submit cookie middleware.
 * Ports CSRFMiddleware from dashboard/main.py:162–252.
 *
 * Pattern:
 *   1. On every response, set a random CSRF token in an HttpOnly cookie.
 *   2. On POST (and other state-changing methods), require the same token
 *      either in the form body field `csrf_token` OR in the header
 *      `X-CSRF-Token` (for fetch/AJAX requests).
 *   3. Exempt: GET, HEAD, OPTIONS, /login, /api/cron/*.
 *
 * The cookie value and submitted token are compared with timingSafeEqual.
 */
import {
  Injectable,
  NestMiddleware,
  Logger,
} from '@nestjs/common';
import { Request, Response, NextFunction } from 'express';
import * as crypto from 'crypto';
import * as timers from 'timers';

export const CSRF_COOKIE = 'smm_csrf';
export const CSRF_FIELD = 'csrf_token';

// Methods that require CSRF validation
const CSRF_PROTECTED_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// Paths exempt from CSRF (login form uses password protection; cron uses CRON_SECRET)
const CSRF_EXEMPT_PATHS_PREFIX = ['/api/cron/'];
const CSRF_EXEMPT_PATHS_EXACT = new Set(['/login', '/login/']);

function generateCsrfToken(): string {
  return crypto.randomBytes(32).toString('hex');
}

function timingSafeCompare(a: string, b: string): boolean {
  try {
    const aBuf = Buffer.from(a);
    const bBuf = Buffer.from(b);
    if (aBuf.length !== bBuf.length) {
      return false;
    }
    return crypto.timingSafeEqual(aBuf, bBuf);
  } catch {
    return false;
  }
}

// Suppress unused import warning — timers is imported for its side effect
void timers;

@Injectable()
export class CsrfMiddleware implements NestMiddleware {
  private readonly logger = new Logger(CsrfMiddleware.name);

  use(req: Request, res: Response, next: NextFunction): void {
    const path = req.path;
    const method = req.method.toUpperCase();

    // Read existing CSRF token from cookie, or generate a new one
    let csrfToken: string =
      (req.cookies as Record<string, string>)[CSRF_COOKIE] ?? '';
    if (!csrfToken) {
      csrfToken = generateCsrfToken();
    }

    // Attach the token to the request so controllers/templates can use it
    (req as Request & { csrfToken?: string }).csrfToken = csrfToken;

    // Always set the CSRF cookie on the response (refresh on every request)
    res.cookie(CSRF_COOKIE, csrfToken, {
      httpOnly: true,
      sameSite: 'strict',
      path: '/',
    });

    // For safe methods or exempt paths, no validation needed
    const isExemptPath =
      CSRF_EXEMPT_PATHS_EXACT.has(path) ||
      CSRF_EXEMPT_PATHS_PREFIX.some((prefix) => path.startsWith(prefix));

    if (!CSRF_PROTECTED_METHODS.has(method) || isExemptPath) {
      return next();
    }

    // For state-changing requests: validate the submitted token
    // Check form body field first, then X-CSRF-Token header
    const bodyToken =
      (req.body as Record<string, string> | undefined)?.[CSRF_FIELD] ?? '';
    const headerToken = (req.headers['x-csrf-token'] as string | undefined) ?? '';
    const submittedToken = bodyToken || headerToken;

    if (
      !csrfToken ||
      !submittedToken ||
      !timingSafeCompare(csrfToken, submittedToken)
    ) {
      this.logger.warn(
        `CSRF validation failed: ${method} ${path} — redirecting`,
      );
      res.redirect(303, `${path}?error=csrf`);
      return;
    }

    next();
  }
}
