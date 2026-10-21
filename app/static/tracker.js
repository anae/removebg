(() => {
  const script = document.currentScript;
  const siteSlug = script?.dataset.site;
  if (!siteSlug || navigator.doNotTrack === "1") return;

  const key = "ananaba:analytics-session";
  let sessionId = sessionStorage.getItem(key);
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem(key, sessionId);
  }

  const payload = JSON.stringify({
    siteSlug,
    pathname: `${location.pathname}${location.search}`,
    referrer: document.referrer,
    sessionId,
  });

  const endpoint = "https://dashboard.ananaba.be/api/ingest";
  if (!navigator.sendBeacon || !navigator.sendBeacon(endpoint, new Blob([payload], { type: "text/plain" }))) {
    fetch(endpoint, { method:"POST", headers:{ "Content-Type":"text/plain" }, body:payload, keepalive:true, mode:"cors" }).catch(() => {});
  }
})();
