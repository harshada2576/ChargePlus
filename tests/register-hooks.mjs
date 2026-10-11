import { register } from "node:module";
import { pathToFileURL } from "node:url";

// Tests receive configuration explicitly from the runner. Never load a
// developer's environment file because it can point tests at production.

register("./hooks.mjs", pathToFileURL("./tests/"));
