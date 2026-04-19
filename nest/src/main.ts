/**
 * NestJS application bootstrap.
 * Listens on port 8001 by default to avoid clashing with the Python
 * dashboard running on port 8000 during the migration period.
 */
import { NestFactory } from '@nestjs/core';
import { Logger } from '@nestjs/common';
import { AppModule } from './app.module';
import { AuthMiddleware } from './auth/auth.middleware';
import { CsrfMiddleware } from './auth/csrf.middleware';
import type { Request, Response, NextFunction } from 'express';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const cookieParser = require('cookie-parser') as () => ReturnType<typeof import('cookie-parser')>;

async function bootstrap(): Promise<void> {
  const logger = new Logger('Bootstrap');
  const app = await NestFactory.create(AppModule);

  // cookie-parser must be registered before auth/CSRF middleware
  // so req.cookies is populated when the middleware runs.
  app.use(cookieParser());

  // Apply auth and CSRF middleware globally via DI-resolved instances.
  // The middleware themselves handle path-based exemptions (/login, /api/cron/*).
  const authMiddleware = app.get(AuthMiddleware);
  const csrfMiddleware = app.get(CsrfMiddleware);

  app.use((req: Request, res: Response, next: NextFunction) => {
    authMiddleware.use(req, res, next);
  });
  app.use((req: Request, res: Response, next: NextFunction) => {
    csrfMiddleware.use(req, res, next);
  });

  // No global prefix — controllers define their own paths to preserve
  // dashboard URL parity with the Python app.

  const port = parseInt(process.env.PORT ?? '8001', 10);
  await app.listen(port);
  logger.log(`Application listening on http://localhost:${port}`);
}

bootstrap();
