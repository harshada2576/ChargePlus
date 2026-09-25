import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

const globalForDb = globalThis as typeof globalThis & {
  __arenaNextJsPostgresqlPool?: Pool;
};

export function getPool(): Pool {
  if (globalForDb.__arenaNextJsPostgresqlPool) {
    return globalForDb.__arenaNextJsPostgresqlPool;
  }
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is required");
  }
  const pool = new Pool({ connectionString: databaseUrl });
  if (process.env.NODE_ENV !== "production") {
    globalForDb.__arenaNextJsPostgresqlPool = pool;
  }
  return pool;
}

export const pool = new Proxy({} as Pool, {
  get(_target, prop, receiver) {
    const actualPool = getPool();
    const val = Reflect.get(actualPool, prop, receiver);
    if (typeof val === "function") {
      return val.bind(actualPool);
    }
    return val;
  },
});

let _db: ReturnType<typeof drizzle> | null = null;
function getDb() {
  if (!_db) {
    _db = drizzle(getPool());
  }
  return _db;
}

export const db = new Proxy({} as ReturnType<typeof drizzle>, {
  get(_target, prop, receiver) {
    const actualDb = getDb();
    const val = Reflect.get(actualDb, prop, receiver);
    if (typeof val === "function") {
      return val.bind(actualDb);
    }
    return val;
  },
});
