/** Opens a prefilled Gmail compose window. Nothing is sent: the user reviews the draft and presses Send in their own Gmail.
 *  Browsers block a window opened after an await, so the tab is opened first (on the click) and pointed at Gmail once the notice is ready. */
export type MailDraft = { to?: string; bcc?: string; subject: string; body: string };

export function openBlankTab(): Window | null {
  try { return window.open("", "_blank"); } catch { return null; }
}

export function gmailUrl(d: MailDraft): string {
  const p = new URLSearchParams({ view: "cm", fs: "1", su: d.subject, body: d.body.slice(0, 1700) });
  if (d.to) p.set("to", d.to);
  if (d.bcc) p.set("bcc", d.bcc);
  return `https://mail.google.com/mail/?${p.toString()}`;
}

/** Points the pre-opened tab at Gmail (or opens a new one). Returns false if the browser blocked it. */
export function showInGmail(tab: Window | null, d: MailDraft): boolean {
  const url = gmailUrl(d);
  if (tab && !tab.closed) { tab.location.href = url; return true; }
  return !!window.open(url, "_blank");
}
