#!/usr/bin/env node
/**
 * Run the external-boundary canaries with the Node runtime shipped in the
 * Codex candidate image.
 *
 * This mirrors feynman_boundary_probe.py without reading protected contents.
 * The evaluator binds the program bytes and verifies the artifact outside the
 * container. It is intended for native Windows host-to-Linux path mapping,
 * where the observed paths are in the container namespace.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BLOCKED_ERRNOS = new Set(["EACCES", "EPERM", "EROFS", "ENOENT", "ENOTDIR"]);
const SECRET_KEY_PATTERN = /(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|AUTH|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)/i;
const PATH_NAMESPACES = new Set(["shared", "container"]);
const SHA_PATTERN = /^[0-9a-f]{64}$/;

function shaBytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function programSha(options) {
  if (options.program_sha256 !== undefined) {
    if (typeof options.program_sha256 !== "string" || !SHA_PATTERN.test(options.program_sha256)) {
      throw new Error("program_sha256 must be lowercase SHA-256");
    }
    return options.program_sha256;
  }
  if (!import.meta.url.startsWith("file:")) {
    throw new Error("program_sha256 is required when the probe is not launched from a file");
  }
  return shaBytes(fs.readFileSync(fileURLToPath(import.meta.url)));
}

function errorRecord(error) {
  return {
    type: error?.name || "Error",
    errno: typeof error?.errno === "number" ? error.errno : null,
    message: String(error?.message || error).slice(0, 240),
  };
}

function pathObservation(value, pathNamespace) {
  const record = { path: path.resolve(value) };
  if (pathNamespace !== "shared") record.path_namespace = pathNamespace;
  return record;
}

function readObservation(value, expectedMarker, pathNamespace) {
  const record = {
    ...pathObservation(value, pathNamespace),
    succeeded: false,
    denied: false,
  };
  try {
    const data = fs.readFileSync(value);
    record.succeeded = true;
    record.bytes = data.length;
    record.sha256 = shaBytes(data);
    if (expectedMarker !== null) {
      const marker = Buffer.from(expectedMarker, "utf8");
      record.expected_marker_sha256 = shaBytes(marker);
      record.marker_match = data.equals(marker);
    }
  } catch (error) {
    record.denied = BLOCKED_ERRNOS.has(error?.code);
    record.error = errorRecord(error);
  }
  return record;
}

function writeObservation(value, marker, pathNamespace) {
  const data = Buffer.from(marker, "utf8");
  const record = {
    ...pathObservation(value, pathNamespace),
    succeeded: false,
    denied: false,
    marker_sha256: shaBytes(data),
  };
  let descriptor = null;
  try {
    descriptor = fs.openSync(value, "wx", 0o600);
    fs.writeSync(descriptor, data);
    fs.fsyncSync(descriptor);
    record.succeeded = true;
  } catch (error) {
    record.denied = BLOCKED_ERRNOS.has(error?.code);
    record.error = errorRecord(error);
  } finally {
    if (descriptor !== null) fs.closeSync(descriptor);
  }
  return record;
}

function networkObservation(host, port, timeoutSeconds) {
  if (host === null || port === null) return { attempted: false };
  return new Promise((resolve) => {
    let completed = false;
    const socket = net.createConnection({ host, port });
    const finish = (connected, error = null) => {
      if (completed) return;
      completed = true;
      socket.destroy();
      const record = { attempted: true, host, port, connected };
      if (error !== null) record.error = errorRecord(error);
      resolve(record);
    };
    socket.setTimeout(timeoutSeconds * 1000, () => {
      const error = new Error("network probe timed out");
      error.code = "ETIMEDOUT";
      finish(false, error);
    });
    socket.once("connect", () => finish(true));
    socket.once("error", (error) => finish(false, error));
  });
}

function required(options, name) {
  const value = options[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`missing required argument: --${name.replaceAll("_", "-")}`);
  }
  return value;
}

function parseArgs(argv) {
  const options = { forbidden_write: [] };
  const repeatable = new Set(["forbidden_write"]);
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2).replaceAll("-", "_");
    if (repeatable.has(key)) {
      options[key].push(argv[++index]);
    } else {
      options[key] = argv[++index];
    }
  }
  return options;
}

async function runProbe(options) {
  const pathNamespace = options.path_namespace || "shared";
  if (!PATH_NAMESPACES.has(pathNamespace)) throw new Error("path_namespace must be shared or container");
  const forbiddenWrites = options.forbidden_write || [];
  if (forbiddenWrites.length === 0) throw new Error("at least one forbidden write path is required");
  const networkHost = options.network_host ?? null;
  const networkPort = options.network_port === undefined ? null : Number(options.network_port);
  if ((networkHost === null) !== (networkPort === null)) {
    throw new Error("network host and port must be supplied together");
  }
  if (networkPort !== null && (!Number.isInteger(networkPort) || networkPort < 1 || networkPort > 65535)) {
    throw new Error("network port must be between 1 and 65535");
  }
  const networkTimeout = options.network_timeout === undefined ? 1.5 : Number(options.network_timeout);
  if (!Number.isFinite(networkTimeout) || networkTimeout <= 0) throw new Error("network timeout must be positive");

  const result = {
    schema_version: 1,
    run_id: required(options, "run_id"),
    boundary_profile_sha256: required(options, "boundary_profile_sha256"),
    probe_program_sha256: programSha(options),
    observations: {
      candidate_read: readObservation(required(options, "candidate_read"), required(options, "candidate_read_marker"), pathNamespace),
      protected_reads: {
        evaluator: readObservation(required(options, "evaluator_read"), null, pathNamespace),
        source: readObservation(required(options, "source_read"), null, pathNamespace),
        real_home: readObservation(required(options, "real_home_read"), null, pathNamespace),
      },
      candidate_write: writeObservation(required(options, "candidate_write"), required(options, "candidate_write_marker"), pathNamespace),
      forbidden_writes: forbiddenWrites.map((value) => writeObservation(value, required(options, "forbidden_write_marker"), pathNamespace)),
      environment: {
        keys: Object.keys(process.env).sort(),
        secret_like_keys: Object.keys(process.env).sort().filter((key) => SECRET_KEY_PATTERN.test(key)),
      },
      network: await networkObservation(networkHost, networkPort, networkTimeout),
    },
    scope: "direct observations inside the supplied boundary; not a proof that the boundary or runner is honest",
  };
  if (pathNamespace !== "shared") result.path_namespace = pathNamespace;
  return result;
}

function writeOutput(output, value) {
  try {
    if (fs.lstatSync(output)) throw new Error(`refusing to overwrite: ${output}`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

try {
  const argv = process.argv.slice(1);
  if (argv[0] === "--") argv.shift();
  const options = parseArgs(argv);
  const result = await runProbe(options);
  writeOutput(required(options, "output"), result);
  console.log(JSON.stringify({
    run_id: result.run_id,
    boundary_profile_sha256: result.boundary_profile_sha256,
    probe_program_sha256: result.probe_program_sha256,
  }, null, 2));
} catch (error) {
  console.error(`error: ${error?.message || error}`);
  process.exitCode = 2;
}
