import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as net.AddressInfo
      server.close(() => resolve(port))
    })
    server.on('error', reject)
  })
}

async function waitForApi(base: string, child: ChildProcess): Promise<void> {
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error('lineage API exited during startup')
    try {
      const response = await fetch(`${base}/projects`)
      if (response.ok) return
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error('lineage API did not start')
}

// Starts the real API on the real SP_CLO lineage DB; UI tests skip when it cannot start.
export default async function setup() {
  const db = process.env.LINEAGE_DB ?? path.join(root, 'outputs/SP_CLO/lineage.db')
  const python = [path.join(root, '.venv/bin/python'), path.join(root, '.venv/Scripts/python.exe')].find(existsSync)
  if (!existsSync(db) || !python) return undefined

  const port = await freePort()
  const base = `http://127.0.0.1:${port}`
  // A long keep-alive stops the server closing an idle socket just as the test client reuses it.
  const child = spawn(python, ['-m', 'uvicorn', 'lineage_api.app:app', '--host', '127.0.0.1', '--port', String(port), '--timeout-keep-alive', '300'], {
    cwd: path.join(root, 'src/api'),
    env: { ...process.env, LINEAGE_DB: db },
    stdio: 'ignore',
  })
  try {
    await waitForApi(base, child)
  } catch (error) {
    child.kill()
    throw error
  }
  process.env.TEST_API_BASE = base
  return () => {
    child.kill()
  }
}
