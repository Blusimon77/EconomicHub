/**
 * Authentication middleware.
 * Ports AuthMiddleware from dashboard/main.py:73–92.
 *
 * Behavior (preserved exactly from Python):
 *   - If DASHBOARD_PASSWORD is empty → skip auth entirely (log WARNING at startup).
 *   - /login and /login/ → always pass through.
 *   - /static/* → always pass through.
 *   - Valid session cookie → pass through.
 *   - Missing/invalid session cookie → redirect to /login.
 */
import {
  Injectable,
  NestMiddleware,
  Logger,
  OnModuleInit,
} from '@nestjs/common';
import { Request, Response, NextFunction } from 'express';
import { AuthService, AUTH_COOKIE } from './auth.service';

// Paths that are always public (no auth check)
const PUBLIC_PATHS = new Set(['/login', '/login/']);

@Injectable()
export class AuthMiddleware implements NestMiddleware, OnModuleInit {
  private readonly logger = new Logger(AuthMiddleware.name);

  constructor(private readonly authService: AuthService) {}

  onModuleInit(): void {
    if (!this.authService.isAuthEnabled()) {
      this.logger.warn(
        'DASHBOARD_PASSWORD is empty — authentication is DISABLED. ' +
          'Set DASHBOARD_PASSWORD in your .env to enable login protection.',
      );
    }
  }

  use(req: Request, res: Response, next: NextFunction): void {
    // If no password configured, skip auth (mirrors Python behavior)
    if (!this.authService.isAuthEnabled()) {
      return next();
    }

    const path = req.path;

    // Public paths — no auth required
    if (PUBLIC_PATHS.has(path)) {
      return next();
    }

    // Static assets — no auth required
    if (path.startsWith('/static')) {
      return next();
    }

    // Cron endpoints are protected by CRON_SECRET header, not session cookie
    if (path.startsWith('/api/cron/')) {
      return next();
    }

    // Health check
    if (path === '/health') {
      return next();
    }

    // Verify session cookie
    const token: string = (req.cookies as Record<string, string>)[AUTH_COOKIE] ?? '';
    if (this.authService.verifySessionToken(token)) {
      return next();
    }

    // Not authenticated — redirect to login
    res.redirect(303, '/login');
  }
}
