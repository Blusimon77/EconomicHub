/**
 * SSRF-safe URL validator.
 * Ports _is_safe_url() from dashboard/main.py:255 with an IPv6 fix.
 *
 * FIX vs Python original (H2 in the migration plan):
 *   The Python version only checks `addr.is_private || addr.is_loopback ||
 *   addr.is_link_local` using Python's ipaddress module, which catches the
 *   most common cases but does not explicitly enumerate IPv6 private prefixes
 *   as a library concern. This port uses ipaddr.js to explicitly check:
 *     - ::1/128    (loopback)
 *     - fc00::/7   (Unique Local Address — ULA)
 *     - fe80::/10  (link-local)
 *   in addition to all IPv4 private ranges, closing the IPv6 gap noted as
 *   finding H2 in the migration plan.
 */
import { Injectable, BadRequestException } from '@nestjs/common';
import * as ipaddr from 'ipaddr.js';

// Private IPv4 CIDR ranges to block (matches Python ipaddress "is_private")
const PRIVATE_IPV4_RANGES: Array<[string, number]> = [
  ['10.0.0.0', 8],
  ['172.16.0.0', 12],
  ['192.168.0.0', 16],
  ['169.254.0.0', 16], // link-local
  ['127.0.0.0', 8],   // loopback
  ['100.64.0.0', 10], // CGNAT / shared address space
  ['192.0.0.0', 24],  // IETF protocol assignments
  ['192.0.2.0', 24],  // TEST-NET-1
  ['198.51.100.0', 24], // TEST-NET-2
  ['203.0.113.0', 24], // TEST-NET-3
  ['240.0.0.0', 4],   // reserved (future use)
];

// Private IPv6 CIDR ranges to block
const PRIVATE_IPV6_RANGES: Array<[string, number]> = [
  ['::1', 128],         // loopback
  ['fc00::', 7],        // Unique Local Address (ULA)
  ['fe80::', 10],       // link-local
  ['::ffff:0:0', 96],  // IPv4-mapped
  ['2001:db8::', 32],  // documentation prefix
  ['100::', 64],       // IPv6 Discard prefix
];

// Hostnames that are always blocked regardless of resolution
const BLOCKED_HOSTNAMES = new Set([
  'localhost',
  'localhost.localdomain',
]);

@Injectable()
export class UrlValidatorService {
  /**
   * Returns true if the URL is safe to fetch (HTTP/HTTPS, non-internal).
   * Mirrors _is_safe_url() in dashboard/main.py:255.
   */
  isSafe(url: string): boolean {
    try {
      const parsed = new URL(url);

      // Only allow HTTP and HTTPS schemes
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return false;
      }

      const hostname = parsed.hostname;
      if (!hostname) {
        return false;
      }

      // Block known internal hostnames
      if (BLOCKED_HOSTNAMES.has(hostname.toLowerCase())) {
        return false;
      }

      // Try to parse hostname as an IP address
      if (ipaddr.isValid(hostname)) {
        const addr = ipaddr.parse(hostname);
        const kind = addr.kind();

        if (kind === 'ipv4') {
          const v4 = addr as ipaddr.IPv4;
          for (const [range, prefix] of PRIVATE_IPV4_RANGES) {
            if (v4.match(ipaddr.parseCIDR(`${range}/${prefix}`))) {
              return false;
            }
          }
        } else if (kind === 'ipv6') {
          const v6 = addr as ipaddr.IPv6;

          // Check if it's an IPv4-mapped IPv6 address (::ffff:x.x.x.x)
          if (v6.isIPv4MappedAddress()) {
            const v4 = v6.toIPv4Address();
            for (const [range, prefix] of PRIVATE_IPV4_RANGES) {
              if (v4.match(ipaddr.parseCIDR(`${range}/${prefix}`))) {
                return false;
              }
            }
          }

          // Check IPv6-specific private ranges
          for (const [range, prefix] of PRIVATE_IPV6_RANGES) {
            if (v6.match(ipaddr.parseCIDR(`${range}/${prefix}`))) {
              return false;
            }
          }
        }
      }
      // If hostname is a domain name (not an IP), it's allowed through.
      // DNS rebinding is a separate concern; SSRF via direct IP is blocked above.

      return true;
    } catch {
      // Invalid URL or parse error — reject
      return false;
    }
  }

  /**
   * Throws BadRequestException if the URL is not safe.
   * Convenience wrapper for use in controllers/services.
   */
  validateOrThrow(url: string): void {
    if (!this.isSafe(url)) {
      throw new BadRequestException(
        `URL non consentito: l'URL punta a un indirizzo interno o non è HTTP/HTTPS`,
      );
    }
  }
}
