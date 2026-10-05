// One control per SSH endpoint; each forward retains its own process and status.
export function groupTunnels(tunnels) {
  const groups = new Map();
  for (const tunnel of tunnels) {
    const host = String(tunnel.ssh_host || '').trim().toLowerCase();
    const port = tunnel.ssh_port || 22;
    const id = JSON.stringify([host || tunnel.id, port]);
    if (!groups.has(id)) groups.set(id, {
      id, name: host ? `${host}${port === 22 ? '' : `:${port}`}` : tunnel.name,
      tunnels: [],
    });
    groups.get(id).tunnels.push(tunnel);
  }
  return [...groups.values()].map(group => {
    const rows = group.tunnels;
    const states = new Set(rows.map(row => row.state));
    const state = states.has('error') ? 'error'
      : states.has('connecting') || states.has('reconnecting') ? 'connecting'
      : states.size === 1 ? rows[0].state : 'partial';
    return {...group, state, desired: rows.every(row => row.desired),
      connected: rows.filter(row => row.state === 'connected').length};
  });
}

export async function controlTunnelGroup(group, request) {
  const action = group.desired ? 'disconnect' : 'connect';
  const results = await Promise.allSettled(group.tunnels.map(tunnel =>
    request(`/api/tunnels/${encodeURIComponent(tunnel.id)}/${action}`, {method:'POST', timeout:15000})
  ));
  return results.flatMap((result, index) => result.status === 'rejected'
    ? [`${group.tunnels[index].name}: ${result.reason?.message || 'Request failed'}`] : []);
}
