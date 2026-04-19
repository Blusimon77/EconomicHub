import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { zodValidate } from './config/configuration';
import { PrismaModule } from './prisma/prisma.module';
import { CommonModule } from './common/common.module';
import { AuthModule } from './auth/auth.module';
import { AuthMiddleware } from './auth/auth.middleware';
import { CsrfMiddleware } from './auth/csrf.middleware';

@Module({
  imports: [
    // Global config — validates env vars via zod on startup
    ConfigModule.forRoot({
      isGlobal: true,
      validate: zodValidate,
      // In production env vars come from the platform (Vercel); locally from .env
      envFilePath: '.env',
    }),
    // Global schedule support for future @Cron() decorators
    ScheduleModule.forRoot(),
    // Prisma singleton — global, so no need to import in feature modules
    PrismaModule,
    // Common utilities (HttpClient, UrlValidator)
    CommonModule,
    // Auth module (session token helpers)
    AuthModule,
  ],
  controllers: [AppController],
  // Expose middleware as providers so NestFactory.get() can resolve them
  providers: [AppService, AuthMiddleware, CsrfMiddleware],
})
export class AppModule {}
