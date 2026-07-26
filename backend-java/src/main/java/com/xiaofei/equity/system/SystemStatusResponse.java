package com.xiaofei.equity.system;

import java.time.Instant;

public record SystemStatusResponse(
		String service,
		String status,
		Instant timestamp) {
}
