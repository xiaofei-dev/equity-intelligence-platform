FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /workspace

COPY backend-java/.mvn backend-java/.mvn
COPY backend-java/mvnw backend-java/pom.xml backend-java/
COPY database/migrations database/migrations
RUN cd backend-java && ./mvnw dependency:go-offline

COPY backend-java/src backend-java/src
RUN cd backend-java && ./mvnw package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S spring && adduser -S spring -G spring
COPY --from=builder /workspace/backend-java/target/*.jar app.jar
USER spring:spring
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
