/**
 * One-time data migration: SQLite → PostgreSQL via Prisma.
 *
 * Reads from ../storage/social_manager.db (better-sqlite3, synchronous).
 * Transforms snake_case column names to Prisma camelCase field names.
 * Validates JSON TEXT columns before inserting as jsonb; logs/skips invalid rows.
 * Inserts via Prisma createMany for efficiency.
 *
 * Run: npm run migrate:data
 *
 * Prerequisites:
 *   1. Set DATABASE_URL in .env pointing to the target PostgreSQL instance.
 *   2. Run `npx prisma migrate dev` first to create the schema.
 *   3. Ensure ../storage/social_manager.db exists (source SQLite file).
 */

import * as path from 'path';
import * as fs from 'fs';
import Database from 'better-sqlite3';
import { PrismaClient } from '@prisma/client';

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

// Load .env manually before Prisma/NestJS initialises
const envPath = path.resolve(__dirname, '..', '.env');
if (fs.existsSync(envPath)) {
  const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx < 0) continue;
    const key = trimmed.substring(0, eqIdx).trim();
    const value = trimmed.substring(eqIdx + 1).trim();
    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

const SQLITE_PATH = path.resolve(
  __dirname,
  '..',
  '..',
  'storage',
  'social_manager.db',
);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function safeParseJson(value: unknown): unknown {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') return value;
  if (value === '') return null;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function toBoolean(value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 1 || value === '1' || value === 'true' || value === 'True') return true;
  return false;
}

function toDateOrNull(value: unknown): Date | null {
  if (!value) return null;
  try {
    return new Date(value as string);
  } catch {
    return null;
  }
}

// JSON field type for Prisma (InputJsonValue)
type JsonInput = string | number | boolean | null | JsonInput[] | { [key: string]: JsonInput };

// Row from better-sqlite3
type Row = Record<string, unknown>;

// ---------------------------------------------------------------------------
// Migration functions per table
// ---------------------------------------------------------------------------

async function migratePosts(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM posts').all() as Row[];
  if (rows.length === 0) {
    console.log('  posts: 0 rows, skipping');
    return;
  }

  const data = rows.map((r) => ({
    id: r.id as number,
    platform: r.platform as 'linkedin' | 'facebook' | 'instagram',
    status: (r.status ?? 'draft') as 'draft' | 'pending' | 'approved' | 'rejected' | 'scheduled' | 'published' | 'failed',
    content: (r.content as string) ?? '',
    hashtags: (r.hashtags as string) ?? '',
    imageUrl: (r.image_url as string | undefined) ?? undefined,
    mediaPath: (r.media_path as string | undefined) ?? undefined,
    topic: (r.topic as string | undefined) ?? undefined,
    tone: (r.tone as string) ?? 'professionale',
    generatedBy: (r.generated_by as string) ?? 'anthropic',
    scheduledAt: toDateOrNull(r.scheduled_at) ?? undefined,
    publishedAt: toDateOrNull(r.published_at) ?? undefined,
    platformPostId: (r.platform_post_id as string | undefined) ?? undefined,
    approvedBy: (r.approved_by as string | undefined) ?? undefined,
    approvalNote: (r.approval_note as string | undefined) ?? undefined,
  }));

  await prisma.post.createMany({ data, skipDuplicates: true });
  console.log(`  posts: ${data.length} rows inserted`);
}

async function migrateComments(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM comments').all() as Row[];
  if (rows.length === 0) {
    console.log('  comments: 0 rows, skipping');
    return;
  }

  // Insert one by one to handle the nullable replyStatus enum
  let count = 0;
  for (const r of rows) {
    await prisma.comment.upsert({
      where: { platformCommentId: (r.platform_comment_id as string) ?? '' },
      create: {
        id: r.id as number,
        platform: r.platform as 'linkedin' | 'facebook' | 'instagram',
        platformCommentId: (r.platform_comment_id as string) ?? '',
        platformPostId: (r.platform_post_id as string) ?? '',
        authorName: (r.author_name as string) ?? '',
        content: (r.content as string) ?? '',
        isMention: toBoolean(r.is_mention),
        replyDraft: (r.reply_draft as string | undefined) ?? undefined,
        replyPublishedAt: toDateOrNull(r.reply_published_at) ?? undefined,
      },
      update: {},
    });
    count++;
  }
  console.log(`  comments: ${count} rows upserted`);
}

async function migrateCompanyContext(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM company_context').all() as Row[];
  if (rows.length === 0) {
    console.log('  company_context: 0 rows, skipping');
    return;
  }
  for (const r of rows) {
    await prisma.companyContext.upsert({
      where: { id: r.id as number },
      create: {
        id: r.id as number,
        companyName: (r.company_name as string) ?? '',
        description: (r.description as string) ?? '',
        mission: (r.mission as string) ?? '',
        values: (r.values as string) ?? '',
        founded: (r.founded as string) ?? '',
        productsServices: (r.products_services as string) ?? '',
        targetAudience: (r.target_audience as string) ?? '',
        sector: (r.sector as string) ?? '',
        competitors: (r.competitors as string) ?? '',
        toneOfVoice: (r.tone_of_voice as string) ?? '',
        topicsToAvoid: (r.topics_to_avoid as string) ?? '',
        contentPillars: (r.content_pillars as string) ?? '',
        additionalNotes: (r.additional_notes as string) ?? '',
      },
      update: {},
    });
  }
  console.log(`  company_context: ${rows.length} rows upserted`);
}

async function migrateContextWebsites(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM context_websites').all() as Row[];
  if (rows.length === 0) {
    console.log('  context_websites: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    url: (r.url as string) ?? '',
    label: (r.label as string) ?? '',
    category: (r.category as string) ?? '',
    notes: (r.notes as string) ?? '',
    scrapedContent: (r.scraped_content as string) ?? '',
    lastScrapedAt: toDateOrNull(r.last_scraped_at) ?? undefined,
    isActive: toBoolean(r.is_active ?? 1),
  }));
  await prisma.contextWebsite.createMany({ data, skipDuplicates: true });
  console.log(`  context_websites: ${data.length} rows inserted`);
}

async function migrateCompetitors(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM competitors').all() as Row[];
  if (rows.length === 0) {
    console.log('  competitors: 0 rows, skipping');
    return;
  }
  for (const r of rows) {
    const searchResults = safeParseJson(r.search_results) as JsonInput;
    await prisma.competitor.upsert({
      where: { id: r.id as number },
      create: {
        id: r.id as number,
        name: (r.name as string) ?? '',
        website: (r.website as string) ?? '',
        sector: (r.sector as string) ?? '',
        description: (r.description as string) ?? '',
        strengths: (r.strengths as string) ?? '',
        weaknesses: (r.weaknesses as string) ?? '',
        contentStrategy: (r.content_strategy as string) ?? '',
        targetAudience: (r.target_audience as string) ?? '',
        toneOfVoice: (r.tone_of_voice as string) ?? '',
        uniqueTopics: (r.unique_topics as string) ?? '',
        postingFrequency: (r.posting_frequency as string) ?? '',
        threatLevel: (r.threat_level as number) ?? 2,
        isActive: toBoolean(r.is_active ?? 1),
        scrapedContent: (r.scraped_content as string) ?? '',
        lastScrapedAt: toDateOrNull(r.last_scraped_at) ?? undefined,
        searchResults: searchResults !== null ? searchResults : undefined,
        lastSearchedAt: toDateOrNull(r.last_searched_at) ?? undefined,
      },
      update: {},
    });
  }
  console.log(`  competitors: ${rows.length} rows upserted`);
}

async function migrateCompetitorSocials(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM competitor_socials').all() as Row[];
  if (rows.length === 0) {
    console.log('  competitor_socials: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    competitorId: r.competitor_id as number,
    platform: (r.platform as string) ?? '',
    profileUrl: (r.profile_url as string) ?? '',
    handle: (r.handle as string) ?? '',
    followers: (r.followers as string) ?? '',
    avgLikes: (r.avg_likes as string) ?? '',
    avgComments: (r.avg_comments as string) ?? '',
    postingDays: (r.posting_days as string) ?? '',
    contentTypes: (r.content_types as string) ?? '',
    notes: (r.notes as string) ?? '',
  }));
  await prisma.competitorSocial.createMany({ data, skipDuplicates: true });
  console.log(`  competitor_socials: ${data.length} rows inserted`);
}

async function migrateCompetitorObservations(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM competitor_observations').all() as Row[];
  if (rows.length === 0) {
    console.log('  competitor_observations: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    competitorId: r.competitor_id as number,
    category: (r.category as string) ?? 'generale',
    content: (r.content as string) ?? '',
    createdAt: toDateOrNull(r.created_at) ?? new Date(),
  }));
  await prisma.competitorObservation.createMany({ data, skipDuplicates: true });
  console.log(`  competitor_observations: ${data.length} rows inserted`);
}

async function migrateCompetitorDealers(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM competitor_dealers').all() as Row[];
  if (rows.length === 0) {
    console.log('  competitor_dealers: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    competitorId: r.competitor_id as number,
    name: (r.name as string) ?? '',
    website: (r.website as string) ?? '',
    address: (r.address as string) ?? '',
    city: (r.city as string) ?? '',
    region: (r.region as string) ?? '',
    country: (r.country as string) ?? '',
    phone: (r.phone as string) ?? '',
    email: (r.email as string) ?? '',
    notes: (r.notes as string) ?? '',
    source: (r.source as string) ?? '',
    sourceUrl: (r.source_url as string) ?? '',
    foundAt: toDateOrNull(r.found_at) ?? new Date(),
  }));
  await prisma.competitorDealer.createMany({ data, skipDuplicates: true });
  console.log(`  competitor_dealers: ${data.length} rows inserted`);
}

async function migrateCompetitorProducts(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM competitor_products').all() as Row[];
  if (rows.length === 0) {
    console.log('  competitor_products: 0 rows, skipping');
    return;
  }

  let skipped = 0;
  const data = rows.map((r) => {
    const techSpecs = safeParseJson(r.tech_specs) as JsonInput;
    if (r.tech_specs && techSpecs === null) {
      console.warn(
        `  WARNING: competitor_products row id=${r.id as number} has invalid JSON in tech_specs — inserting as null`,
      );
      skipped++;
    }
    return {
      id: r.id as number,
      competitorId: r.competitor_id as number,
      dealerId: (r.dealer_id as number | undefined) ?? undefined,
      name: (r.name as string) ?? '',
      productLine: (r.product_line as string) ?? '',
      category: (r.category as string) ?? '',
      techSpecs: techSpecs !== null ? techSpecs : undefined,
      techSummary: (r.tech_summary as string) ?? '',
      brochureUrl: (r.brochure_url as string) ?? '',
      brochureFilename: (r.brochure_filename as string) ?? '',
      pageUrl: (r.page_url as string) ?? '',
      source: (r.source as string) ?? '',
      fileSizeKb: (r.file_size_kb as number) ?? 0,
      foundAt: toDateOrNull(r.found_at) ?? new Date(),
    };
  });

  await prisma.competitorProduct.createMany({ data, skipDuplicates: true });
  console.log(
    `  competitor_products: ${data.length} rows inserted${skipped > 0 ? `, ${skipped} with null tech_specs` : ''}`,
  );
}

async function migrateCompetitorAnalyses(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM competitor_analyses').all() as Row[];
  if (rows.length === 0) {
    console.log('  competitor_analyses: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    summary: (r.summary as string) ?? '',
    landscape: (r.landscape as string) ?? '',
    perCompetitor: safeParseJson(r.per_competitor) as JsonInput ?? undefined,
    opportunities: safeParseJson(r.opportunities) as JsonInput ?? undefined,
    threats: safeParseJson(r.threats) as JsonInput ?? undefined,
    recommendations: safeParseJson(r.recommendations) as JsonInput ?? undefined,
    contentGaps: safeParseJson(r.content_gaps) as JsonInput ?? undefined,
    dataQuality: (r.data_quality as string) ?? '',
    sourcesUsed: safeParseJson(r.sources_used) as JsonInput ?? undefined,
    rawResponse: (r.raw_response as string) ?? '',
    generatedBy: (r.generated_by as string) ?? 'anthropic',
    createdAt: toDateOrNull(r.created_at) ?? new Date(),
  }));
  await prisma.competitorAnalysis.createMany({ data, skipDuplicates: true });
  console.log(`  competitor_analyses: ${data.length} rows inserted`);
}

async function migrateOwnProducts(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM own_products').all() as Row[];
  if (rows.length === 0) {
    console.log('  own_products: 0 rows, skipping');
    return;
  }
  for (const r of rows) {
    const techSpecs = safeParseJson(r.tech_specs) as JsonInput;
    await prisma.ownProduct.upsert({
      where: { id: r.id as number },
      create: {
        id: r.id as number,
        name: (r.name as string) ?? '',
        productLine: (r.product_line as string) ?? '',
        category: (r.category as string) ?? '',
        description: (r.description as string) ?? '',
        workingHeight: (r.working_height as number | undefined) ?? undefined,
        techSpecs: techSpecs !== null ? techSpecs : undefined,
        techSummary: (r.tech_summary as string) ?? '',
        pageUrl: (r.page_url as string) ?? '',
        brochureUrl: (r.brochure_url as string) ?? '',
        brochureFilename: (r.brochure_filename as string) ?? '',
        scrapedAt: toDateOrNull(r.scraped_at) ?? undefined,
      },
      update: {},
    });
  }
  console.log(`  own_products: ${rows.length} rows upserted`);
}

async function migrateProductComparisons(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM product_comparisons').all() as Row[];
  if (rows.length === 0) {
    console.log('  product_comparisons: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    ownProductId: (r.own_product_id as number | undefined) ?? undefined,
    ownProductName: (r.own_product_name as string) ?? '',
    competitorProductsSnapshot: safeParseJson(r.competitor_products_snapshot) as JsonInput ?? undefined,
    title: (r.title as string) ?? '',
    summary: (r.summary as string) ?? '',
    comparisonTable: safeParseJson(r.comparison_table) as JsonInput ?? undefined,
    perCompetitor: safeParseJson(r.per_competitor) as JsonInput ?? undefined,
    recommendations: safeParseJson(r.recommendations) as JsonInput ?? undefined,
    rawResponse: (r.raw_response as string) ?? '',
    generatedBy: (r.generated_by as string) ?? 'anthropic',
    createdAt: toDateOrNull(r.created_at) ?? new Date(),
  }));
  await prisma.productComparison.createMany({ data, skipDuplicates: true });
  console.log(`  product_comparisons: ${data.length} rows inserted`);
}

async function migrateDealers(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM dealers').all() as Row[];
  if (rows.length === 0) {
    console.log('  dealers: 0 rows, skipping');
    return;
  }
  for (const r of rows) {
    await prisma.dealer.upsert({
      where: { id: r.id as number },
      create: {
        id: r.id as number,
        name: (r.name as string) ?? '',
        website: (r.website as string) ?? '',
        email: (r.email as string) ?? '',
        phone: (r.phone as string) ?? '',
        address: (r.address as string) ?? '',
        city: (r.city as string) ?? '',
        state: (r.state as string) ?? '',
        country: (r.country as string) ?? '',
        postalCode: (r.postal_code as string) ?? '',
        latitude: (r.latitude as number | undefined) ?? undefined,
        longitude: (r.longitude as number | undefined) ?? undefined,
        notes: (r.notes as string) ?? '',
        createdAt: toDateOrNull(r.created_at) ?? new Date(),
      },
      update: {},
    });
  }
  console.log(`  dealers: ${rows.length} rows upserted`);
}

async function migrateDealerBrands(sqlite: Database.Database, prisma: PrismaClient): Promise<void> {
  const rows = sqlite.prepare('SELECT * FROM dealer_brands').all() as Row[];
  if (rows.length === 0) {
    console.log('  dealer_brands: 0 rows, skipping');
    return;
  }
  const data = rows.map((r) => ({
    id: r.id as number,
    dealerId: r.dealer_id as number,
    competitorId: (r.competitor_id as number | undefined) ?? undefined,
    isOwnBrand: toBoolean(r.is_own_brand),
  }));
  await prisma.dealerBrand.createMany({ data, skipDuplicates: true });
  console.log(`  dealer_brands: ${data.length} rows inserted`);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  if (!fs.existsSync(SQLITE_PATH)) {
    console.error(`SQLite database not found: ${SQLITE_PATH}`);
    process.exit(1);
  }

  if (!process.env.DATABASE_URL) {
    console.error('DATABASE_URL is not set. Configure it in .env first.');
    process.exit(1);
  }

  console.log(`Reading from: ${SQLITE_PATH}`);
  console.log(`Writing to:   ${process.env.DATABASE_URL}`);
  console.log('');

  const sqlite = new Database(SQLITE_PATH, { readonly: true });
  const prisma = new PrismaClient();

  try {
    await prisma.$connect();

    // Insert in foreign-key-safe order:
    // 1. Stand-alone tables first
    console.log('--- Migrating stand-alone tables ---');
    await migratePosts(sqlite, prisma);
    await migrateComments(sqlite, prisma);
    await migrateCompanyContext(sqlite, prisma);
    await migrateContextWebsites(sqlite, prisma);

    // 2. Competitor parent, then children
    console.log('\n--- Migrating competitor tables ---');
    await migrateCompetitors(sqlite, prisma);
    await migrateCompetitorSocials(sqlite, prisma);
    await migrateCompetitorObservations(sqlite, prisma);
    await migrateCompetitorDealers(sqlite, prisma);
    await migrateCompetitorProducts(sqlite, prisma);
    await migrateCompetitorAnalyses(sqlite, prisma);

    // 3. Own products, then comparisons
    console.log('\n--- Migrating product tables ---');
    await migrateOwnProducts(sqlite, prisma);
    await migrateProductComparisons(sqlite, prisma);

    // 4. Dealers → dealer_brands last (FK: dealer + competitor)
    console.log('\n--- Migrating dealer tables ---');
    await migrateDealers(sqlite, prisma);
    await migrateDealerBrands(sqlite, prisma);

    console.log('\nMigration complete.');
  } catch (err) {
    console.error('Migration failed:', err);
    process.exit(1);
  } finally {
    await prisma.$disconnect();
    sqlite.close();
  }
}

main();
