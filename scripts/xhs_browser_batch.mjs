/**
 * Fast, resumable Xiaohongshu helpers for the Browser skill's DOM-CUA API.
 *
 * Keep page reads at dependency boundaries and use the low-level visible-DOM
 * input/click channel for routine reversible form actions. Do not use these
 * helpers for uploads, deletes, or final publish controls.
 */

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function exactVisibleNodeId(visibleDom, visibleText) {
  const source = String(visibleDom || '');
  const exact = escapeRegExp(String(visibleText || '').trim());
  const linePattern = new RegExp(
    `^<[^>]+node_id=(?:"|')?(\\d+)(?:"|')?[^>]*>\\s*${exact}\\s*</[^>]+>$`,
    'gmi',
  );
  const matches = [...source.matchAll(linePattern)].map(match => match[1]);
  const unique = [...new Set(matches)];
  if (unique.length !== 1) {
    throw new Error(`Expected one visible node for ${visibleText}; found ${unique.length}`);
  }
  return unique[0];
}

export async function readVisibleDom(tab) {
  return String(await tab.dom_cua.get_visible_dom());
}

export async function clickExactVisibleNode(tab, visibleDom, visibleText) {
  const nodeId = exactVisibleNodeId(visibleDom, visibleText);
  await tab.dom_cua.click({ node_id: nodeId });
  return { visibleText, nodeId };
}

export async function typeAtCurrentFocus(tab, text) {
  await tab.dom_cua.type({ text: String(text) });
  return { typed: String(text) };
}

export async function keypressAtCurrentFocus(tab, keys) {
  await tab.dom_cua.keypress({ keys: [...keys] });
  return { keys: [...keys] };
}

