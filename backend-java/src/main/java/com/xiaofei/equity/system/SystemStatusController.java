package com.xiaofei.equity.system;

import java.time.Instant;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/system")
public class SystemStatusController {

	@GetMapping("/status")
	public ResponseEntity<SystemStatusResponse> status() {
		return ResponseEntity.ok(new SystemStatusResponse(
				"backend-java",
				"UP",
				Instant.now()));
	}
}
