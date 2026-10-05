import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../codester/static/tunnel-groups.js', import.meta.url), 'utf8');
const {groupTunnels, controlTunnelGroup} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const forward = (id, changes = {}) => ({id, name:id, ssh_host:'server', ssh_port:22, state:'disconnected', desired:false, ...changes});
const groups = groupTunnels([
  forward('a'), forward('b', {ssh_host:'SERVER'}),
  forward('c', {ssh_port:2222}), forward('d', {ssh_host:'other'}),
]);
assert.equal(groups.length, 3);
assert.deepEqual(groups[0].tunnels.map(row => row.id), ['a', 'b']);
assert.equal(groupTunnels([forward('a', {state:'connected', desired:true}), forward('b')])[0].state, 'partial');
assert.equal(groupTunnels([forward('a', {state:'connected'}), forward('b', {state:'error'})])[0].state, 'error');
assert.equal(groupTunnels([forward('a', {state:'connected'}), forward('b', {state:'reconnecting'})])[0].state, 'connecting');
assert.equal(groupTunnels([forward('a', {state:'connected'}), forward('b', {state:'connected'})])[0].state, 'connected');
const calls = [];
const failures = await controlTunnelGroup(groups[0], async path => {
  calls.push(path);
  if (path.includes('/a/')) throw new Error('Port occupied');
});
assert.deepEqual(calls.sort(), ['/api/tunnels/a/connect', '/api/tunnels/b/connect']);
assert.deepEqual(failures, ['a: Port occupied']);
calls.length = 0;
await controlTunnelGroup({...groups[0], desired:true}, async path => calls.push(path));
assert.deepEqual(calls.sort(), ['/api/tunnels/a/disconnect', '/api/tunnels/b/disconnect']);
console.log('Tunnel grouping, mixed states, scoped controls and partial failures passed');
