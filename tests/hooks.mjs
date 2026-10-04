import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    const rel = specifier.slice(2);
    const abs = path.resolve("./src", rel);
    for (const ext of ["", ".ts", ".tsx", "/index.ts"]) {
      if (fs.existsSync(abs + ext) && !fs.statSync(abs + ext).isDirectory()) {
        return {
          shortCircuit: true,
          url: pathToFileURL(abs + ext).href,
        };
      }
    }
  }

  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    if (context.parentURL && context.parentURL.startsWith("file:")) {
      const parentDir = path.dirname(fileURLToPath(context.parentURL));
      const target = path.resolve(parentDir, specifier);
      for (const ext of [".ts", ".tsx", "/index.ts"]) {
        if (fs.existsSync(target + ext) && !fs.statSync(target + ext).isDirectory()) {
          return {
            shortCircuit: true,
            url: pathToFileURL(target + ext).href,
          };
        }
      }
    }
  }

  return nextResolve(specifier, context);
}
