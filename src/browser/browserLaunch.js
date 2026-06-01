export function browserChannel() {
  const channel = process.env.MEGANT_BROWSER_CHANNEL || 'msedge';
  return channel === 'bundled' ? null : channel;
}

export function browserArgs(extraArgs = []) {
  const envArgs = (process.env.MEGANT_BROWSER_ARGS || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

  return [
    ...envArgs,
    ...extraArgs
  ];
}

export function browserLaunchOptions(options = {}) {
  const channel = browserChannel();
  return {
    ...(channel ? { channel } : {}),
    headless: false,
    acceptDownloads: true,
    viewport: { width: 1440, height: 960 },
    ...options,
    args: browserArgs(options.args || [])
  };
}
