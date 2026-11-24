"""Publishing adapter boundary.

The MVP never pretends a post was published. Platform OAuth/API integrations must be
configured and approved before enabling live publishing. Each platform has different
account, media-hosting, review and permission requirements.
"""
def publish_job(job):
    platforms = job.get("platforms", [])
    return {
        "status": "awaiting_integration",
        "platforms": platforms,
        "message": "Video hazır. Canlı yayın için ilgili platformun resmi API OAuth bağlantısı henüz kurulmadı."
    }
