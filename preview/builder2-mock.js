// Explicit offline lookup transport fixtures only. No duplicated product routes.
export async function builder2Mock(path, opts) {
  if (path !== '/builder/lookup') return undefined;
  if (opts.body.confirm !== true) throw Error('Explicit confirmation required');
  window.__builderLookups = (window.__builderLookups || 0) + 1;
  return {results:opts.body.kind === 'city'
    ? [{name:'Louisville',admin1:'Kentucky',country:'United States',latitude:38.25,longitude:-85.76}]
    : [{name:'Counter-Strike 2',appid:730}]};
}
