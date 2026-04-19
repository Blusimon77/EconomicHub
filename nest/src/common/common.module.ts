import { Global, Module } from '@nestjs/common';
import { HttpClientService } from './http-client.service';
import { UrlValidatorService } from './url-validator.service';

/**
 * Global module exposing utility services to every other module without
 * requiring explicit imports.
 */
@Global()
@Module({
  providers: [HttpClientService, UrlValidatorService],
  exports: [HttpClientService, UrlValidatorService],
})
export class CommonModule {}
