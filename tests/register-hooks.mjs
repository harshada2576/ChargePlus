import { existsSync } from "node:fs";
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { config } from "dotenv";

config();
if (existsSync(".env.local")) {
  config({ path: ".env.local", override: true });
}

register("./hooks.mjs", pathToFileURL("./tests/"));
