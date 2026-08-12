vcl 4.1;

# Varnish in front of the artifact API (ADR-0011).
#
# The workload suits an HTTP cache for three reasons established elsewhere:
# every request is byte-identical because personalisation is client-side
# (ADR-0009); the response is regenerated on a tick rather than per request
# (ADR-0008); and one class must be dropped the instant its window closes.
#
# The failure this exists to prevent is not steady-state load — 100 readers
# against a 396 KB file is trivial, measured at p50 0.7ms even from Python's
# stdlib server. It is the **expiry instant**: when a TTL lapses, every reader
# misses at once and hits the backend simultaneously. Request coalescing is on
# by default in Varnish and collapses those into a single backend fetch, which
# is the specific answer to the brief's concurrency requirement.

backend api {
    .host = "api";
    .port = "8088";
    .first_byte_timeout = 30s;
}

# Only these may purge. In a real deployment this is the refresh job's address;
# here it is the compose network.
acl purgers {
    "localhost";
    "127.0.0.1";
    "172.16.0.0"/12;
    "192.168.0.0"/16;
}

sub vcl_recv {
    # BAN is how ADR-0009's event-driven invalidation is expressed: when the
    # refresh job closes a window, it bans the class-3 artifacts and the stale
    # ones are gone immediately rather than lingering out their TTL.
    if (req.method == "BAN") {
        if (!client.ip ~ purgers) {
            return (synth(403, "not allowed"));
        }
        ban("obj.http.X-Artifact-Class == " + req.http.X-Ban-Class);
        return (synth(200, "banned class " + req.http.X-Ban-Class));
    }

    if (req.method == "PURGE") {
        if (!client.ip ~ purgers) {
            return (synth(403, "not allowed"));
        }
        return (purge);
    }

    # The ops feed is per-moment by definition and must never be cached.
    if (req.url ~ "^/artifact/ops") {
        return (pass);
    }

    unset req.http.Cookie;
    return (hash);
}

sub vcl_backend_response {
    # Honour the per-class Cache-Control the API sets; it is derived from
    # measurement (ADR-0009), not from a global guess.
    set beresp.http.X-Artifact-Class = beresp.http.X-Artifact-Class;

    # Serve stale while revalidating, and keep objects briefly past TTL so a
    # backend blip degrades freshness rather than availability.
    set beresp.grace = 10s;
    set beresp.keep = 60s;

    # A 503 from a class that has not run yet must not be remembered.
    if (beresp.status >= 500) {
        set beresp.uncacheable = true;
        set beresp.ttl = 0s;
    }
    return (deliver);
}

sub vcl_deliver {
    # Hit/miss on the response so the load test can count them without parsing
    # varnishstat, and so a human can see cache behaviour in curl output.
    if (obj.hits > 0) {
        set resp.http.X-Cache = "HIT";
    } else {
        set resp.http.X-Cache = "MISS";
    }
    set resp.http.X-Cache-Hits = obj.hits;
    return (deliver);
}
