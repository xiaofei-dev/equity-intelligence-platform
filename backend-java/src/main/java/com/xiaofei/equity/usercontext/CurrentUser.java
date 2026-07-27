package com.xiaofei.equity.usercontext;

import java.util.UUID;

public record CurrentUser(UUID userId, UUID identityId, String externalSubject) {
}
