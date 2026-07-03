import ssl
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from urllib3.util.retry import Retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LegacySSLAdapter(HTTPAdapter):
    """
    HTTPS adapter for government and legacy Indian travel APIs (IRCTC Air, IRCTC Hotels, RailYatri)
    that require relaxed TLS security levels and disabled certificate verification.

    Enables the SSL_OP_LEGACY_SERVER_CONNECT option (0x4) for hosts that reject
    modern renegotiation, and the module suppresses the resulting
    InsecureRequestWarning noise for these endpoints.
    """

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.options |= 0x4
        except Exception:
            pass
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
            cert_reqs="CERT_NONE",
        )


def build_legacy_session(total_retries: int = 2, backoff_factor: float = 0.5) -> requests.Session:
    """
    Builds a requests Session dedicated to the legacy Indian travel APIs.

    The relaxed TLS adapter is intentionally scoped to this session only — it must
    never be used for general-purpose HTTPS. The session also retries transient
    failures (timeouts, 429/5xx) with exponential backoff. All calls here are
    read-only searches/lookups, so retrying POSTs is safe (no bookings).
    """
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", LegacySSLAdapter(max_retries=retry))
    return session
