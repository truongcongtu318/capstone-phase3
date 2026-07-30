// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// rebuild-sync (retry after checkout main.go fix): touch to build alongside frontend-proxy/accounting/cart/checkout/product-reviews/recommendation under one CI tag
package main

//go:generate go install google.golang.org/protobuf/cmd/protoc-gen-go
//go:generate go install google.golang.org/grpc/cmd/protoc-gen-go-grpc
//go:generate protoc --go_out=./ --go-grpc_out=./ --proto_path=../../pb ../../pb/demo.proto

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/lib/pq"
	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	otelcodes "go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/log/global"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.38.0"
	"go.opentelemetry.io/otel/trace"

	otelhooks "github.com/open-feature/go-sdk-contrib/hooks/open-telemetry/pkg"
	flagd "github.com/open-feature/go-sdk-contrib/providers/flagd/pkg"
	"github.com/open-feature/go-sdk/openfeature"
	pb "github.com/opentelemetry/techx-corp/src/product-catalog/genproto/oteldemo"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"

	"github.com/XSAM/otelsql"
)

type productCatalog struct {
	pb.UnimplementedProductCatalogServiceServer
}

var (
	logger            *slog.Logger
	resource          *sdkresource.Resource
	initResourcesOnce sync.Once
	db                *sql.DB
	reg               metric.Registration
	// catalogCache is the in-memory canonical snapshot that every customer read
	// path (list/get/search) serves from. It is the heart of M9-01: the product
	// read path never touches the DB on the request path, so an RDS
	// failover/reboot/rotation blip cannot fail a customer browse.
	catalogCache *productCache
)

const (
	// cacheSchemaRevision is bumped whenever the in-memory snapshot layout
	// changes. Readiness requires the live snapshot's revision to match this
	// value, so a rolling deploy that changes the cache schema never serves an
	// out-of-schema snapshot into K8s endpoints. (§3.1 "cache revision khớp app revision".)
	cacheSchemaRevision = "v1"

	// cacheRefreshInterval is the background refresh cadence once primed. A
	// failed refresh keeps the last-known-good snapshot (never clears it).
	cacheRefreshInterval = 30 * time.Second
	// primeRetryInterval / primeRetryMax bound the startup/outage prime backoff.
	// While unprimed the pod stays NOT_SERVING (out of endpoints) — this is the
	// startup latch: a cold-start during a DB outage must not enter endpoints
	// with an empty cache.
	primeRetryInterval = 2 * time.Second
	primeRetryMax      = 30 * time.Second
	// dbAttemptTimeout bounds a single DB load attempt so retries actually cycle
	// instead of blocking on a dead TCP connection. This is the refresh path,
	// not the customer path (customer reads are pure in-memory).
	dbAttemptTimeout = 2 * time.Second
)

// retryBackoffs implements the short blip retry (§3.2): 4 attempts total with
// 100/200/400ms backoff between them (700ms of waiting), transient errors only.
var retryBackoffs = []time.Duration{
	100 * time.Millisecond,
	200 * time.Millisecond,
	400 * time.Millisecond,
}

// Freshness / reliability metrics (§3.1). OTel instrument names map to these
// Prometheus series (counters get a _total suffix from the Prometheus exporter):
//
//	cache_primed            gauge   1 = snapshot present and schema-valid
//	ever_primed             gauge   1 = latch has fired at least once
//	cache_age_seconds       gauge   seconds since last successful refresh
//	served_stale_total      counter customer reads served from stale LKG cache
//	db_retry_attempts_total counter transient retry attempts on refresh
//	db_retry_recovered_total counter refreshes that succeeded after >=1 retry
//	db_retry_exhausted_total counter refreshes that failed after all retries
var (
	servedStaleCounter metric.Int64Counter
	dbRetryAttempts    metric.Int64Counter
	dbRetryRecovered   metric.Int64Counter
	dbRetryExhausted   metric.Int64Counter
	cacheMetricsReg    metric.Registration
)

func init() {
	logger = otelslog.NewLogger("product-catalog")
}

func initResource() *sdkresource.Resource {
	initResourcesOnce.Do(func() {
		extraResources, _ := sdkresource.New(
			context.Background(),
			sdkresource.WithOS(),
			sdkresource.WithProcess(),
			sdkresource.WithContainer(),
			sdkresource.WithHost(),
		)
		resource, _ = sdkresource.Merge(
			sdkresource.Default(),
			extraResources,
		)
	})
	return resource
}

func initTracerProvider() *sdktrace.TracerProvider {
	ctx := context.Background()

	exporter, err := otlptracegrpc.New(ctx)
	if err != nil {
		logger.Error(fmt.Sprintf("OTLP Trace gRPC Creation: %v", err))

	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(initResource()),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	return tp
}

func initMeterProvider() *sdkmetric.MeterProvider {
	ctx := context.Background()

	exporter, err := otlpmetricgrpc.New(ctx)
	if err != nil {
		logger.Error(fmt.Sprintf("new otlp metric grpc exporter failed: %v", err))
	}

	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(exporter)),
		sdkmetric.WithResource(initResource()),
	)
	otel.SetMeterProvider(mp)
	return mp
}

func initLoggerProvider() *sdklog.LoggerProvider {
	ctx := context.Background()

	logExporter, err := otlploggrpc.New(ctx)
	if err != nil {
		return nil
	}

	loggerProvider := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewBatchProcessor(logExporter)),
	)
	global.SetLoggerProvider(loggerProvider)

	return loggerProvider
}

// initDatabase opens the pooled DB handle and registers pool metrics. It does
// NOT block on DB reachability: M9-01 decouples process/server start from the DB
// so a pod can come up, latch NOT_SERVING, and prime once the DB is reachable —
// instead of crash-looping (the old REL-14 retry-then-exit behaviour). A dead DB
// is handled by the cache prime loop + readiness latch, not by refusing to start.
func initDatabase() error {
	connStr := os.Getenv("DB_CONNECTION_STRING")
	if connStr == "" {
		return fmt.Errorf("DB_CONNECTION_STRING environment variable not set")
	}

	var err error
	db, err = otelsql.Open("postgres", connStr,
		otelsql.WithAttributes(semconv.DBSystemNamePostgreSQL),
		otelsql.WithSpanOptions(otelsql.SpanOptions{
			OmitConnResetSession: true,
			OmitRows:             true,
		}))
	if err != nil {
		return fmt.Errorf("failed to open database connection: %w", err)
	}

	// REL-05 (INC-1 root cause): bound the client-side connection pool. Without
	// this, database/sql defaults to unlimited open connections, so under load
	// product-catalog can exhaust Postgres max_connections - and Postgres here is
	// shared with product-reviews + accounting, so leave headroom for them too.
	// With M9-01 the customer read path no longer hits the DB (only the ~30s
	// refresh does), so real pool pressure from this service is now tiny.
	db.SetMaxOpenConns(20)
	db.SetMaxIdleConns(10)
	// M9-01 (§3.2): shorten connection lifetime 5m -> 60s so stale connections
	// pinned to a pre-failover RDS endpoint are recycled quickly after a
	// failover/reboot, tightening the window a refresh can hit a dead conn.
	db.SetConnMaxLifetime(60 * time.Second)

	reg, err = otelsql.RegisterDBStatsMetrics(db, otelsql.WithAttributes(semconv.DBSystemNamePostgreSQL))
	if err != nil {
		return fmt.Errorf("failed to register database metrics: %w", err)
	}

	logger.Info("Database handle opened (lazy connect; cache prime loop will connect)")
	return nil
}

// ---------------------------------------------------------------------------
// M9-01: in-memory canonical snapshot + startup-latch readiness state machine
// ---------------------------------------------------------------------------

// productSnapshot is an immutable, atomically-swapped last-known-good view of the
// whole catalog. Once built it is never mutated, so readers load the pointer and
// read without locking; a refresh builds a new snapshot and swaps the pointer.
type productSnapshot struct {
	revision string
	products []*pb.Product // sorted by id (query ORDER BY p.id)
	byID     map[string]*pb.Product
	loadedAt time.Time // when this data was successfully fetched from the DB
}

// productCache holds the current snapshot plus the latch/degraded flags that
// drive readiness and the freshness metrics.
type productCache struct {
	revision   string
	snap       atomic.Pointer[productSnapshot]
	everPrimed atomic.Bool // latch: flips true on first full prime, never back
	stale      atomic.Bool // true while the last refresh attempt failed (serving LKG)
	shutdown   atomic.Bool // set on SIGTERM so readiness fails for graceful drain
}

func newProductCache() *productCache {
	return &productCache{revision: cacheSchemaRevision}
}

func buildSnapshot(revision string, products []*pb.Product) *productSnapshot {
	byID := make(map[string]*pb.Product, len(products))
	for _, p := range products {
		byID[p.Id] = p
	}
	return &productSnapshot{
		revision: revision,
		products: products,
		byID:     byID,
		loadedAt: time.Now(),
	}
}

func (c *productCache) current() *productSnapshot { return c.snap.Load() }

// store swaps in a fresh snapshot, fires the ever_primed latch, and clears stale.
func (c *productCache) store(products []*pb.Product) {
	c.snap.Store(buildSnapshot(c.revision, products))
	c.everPrimed.Store(true)
	c.stale.Store(false)
}

// schemaValid reports whether the live snapshot matches the app's schema revision.
func (c *productCache) schemaValid() bool {
	s := c.current()
	return s != nil && s.revision == c.revision
}

// ready is the readiness predicate. STARTUP: false until ever_primed. STEADY:
// Ready = !shutdown && cache_schema_valid. DB reachability is deliberately NOT
// part of this — it is only a degraded signal (cache_age_seconds / served_stale).
func (c *productCache) ready() bool {
	return c.everPrimed.Load() && !c.shutdown.Load() && c.schemaValid()
}

var errCacheNotPrimed = errors.New("catalog cache not primed")

// list/get/search serve purely from the in-memory snapshot. They return
// errCacheNotPrimed only before the first prime, which cannot coincide with a
// customer request because readiness latches on prime (pod not in endpoints).

func (c *productCache) list() ([]*pb.Product, error) {
	s := c.current()
	if s == nil {
		return nil, errCacheNotPrimed
	}
	return s.products, nil
}

func (c *productCache) get(id string) (*pb.Product, bool, error) {
	s := c.current()
	if s == nil {
		return nil, false, errCacheNotPrimed
	}
	p, ok := s.byID[id]
	return p, ok, nil
}

func (c *productCache) search(query string) ([]*pb.Product, error) {
	s := c.current()
	if s == nil {
		return nil, errCacheNotPrimed
	}
	// Preserve the original SQL semantics: case-insensitive substring match on
	// name OR description, results ordered by id (snapshot is already id-sorted).
	q := strings.ToLower(query)
	var out []*pb.Product
	for _, p := range s.products {
		if strings.Contains(strings.ToLower(p.Name), q) ||
			strings.Contains(strings.ToLower(p.Description), q) {
			out = append(out, p)
		}
	}
	return out, nil
}

// recordServedStale increments served_stale_total when a customer read is served
// while the cache is stale (last refresh failed, i.e. we are in a DB outage).
func recordServedStale(ctx context.Context, rpc string) {
	if catalogCache != nil && catalogCache.stale.Load() && servedStaleCounter != nil {
		servedStaleCounter.Add(ctx, 1, metric.WithAttributes(attribute.String("rpc", rpc)))
	}
}

// isTransientDBError classifies errors worth a short retry (§3.2): dropped
// connections and Postgres "shutting down / cannot connect now" states that a
// failover/reboot produces briefly. Permanent errors are not retried.
func isTransientDBError(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, driver.ErrBadConn) || errors.Is(err, sql.ErrConnDone) {
		return true
	}
	var netErr net.Error
	if errors.As(err, &netErr) {
		return true
	}
	var pqErr *pq.Error
	if errors.As(err, &pqErr) {
		switch string(pqErr.Code) {
		// 57P01 admin_shutdown, 57P02 crash_shutdown, 57P03 cannot_connect_now,
		// 08xxx connection exceptions, 53300 too_many_connections.
		case "57P01", "57P02", "57P03", "08000", "08001", "08004", "08006", "53300":
			return true
		}
		return false
	}
	// Some driver-level connection losses surface as plain errors.
	msg := err.Error()
	return strings.Contains(msg, "bad connection") ||
		strings.Contains(msg, "connection refused") ||
		strings.Contains(msg, "connection reset") ||
		strings.Contains(msg, "broken pipe") ||
		strings.Contains(msg, "i/o timeout") ||
		strings.Contains(msg, "no route to host")
}

// loadWithRetry runs load with up to 4 attempts and 100/200/400ms backoff (700ms
// of waiting) for transient blips, each attempt bounded by dbAttemptTimeout. Used
// by the prime/refresh path only — never on the customer request path.
func loadWithRetry(ctx context.Context, load func(context.Context) ([]*pb.Product, error)) ([]*pb.Product, error) {
	var lastErr error
	for attempt := 0; attempt <= len(retryBackoffs); attempt++ {
		if attempt > 0 {
			if dbRetryAttempts != nil {
				dbRetryAttempts.Add(ctx, 1)
			}
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(retryBackoffs[attempt-1]):
			}
		}

		attemptCtx, cancel := context.WithTimeout(ctx, dbAttemptTimeout)
		products, err := load(attemptCtx)
		cancel()
		if err == nil {
			if attempt > 0 && dbRetryRecovered != nil {
				dbRetryRecovered.Add(ctx, 1)
			}
			return products, nil
		}
		lastErr = err
		if !isTransientDBError(err) {
			return nil, lastErr
		}
	}
	if dbRetryExhausted != nil {
		dbRetryExhausted.Add(ctx, 1)
	}
	return nil, lastErr
}

// refreshOnce loads a fresh snapshot from the DB and swaps it in.
func (c *productCache) refreshOnce(ctx context.Context) error {
	return c.refreshWith(ctx, loadProductsFromDB)
}

// refreshWith is the testable core of a refresh: run load (with the blip retry)
// and swap the result in. On failure it marks the cache stale and KEEPS the
// last-known-good snapshot — the cache is never cleared because of a DB error.
func (c *productCache) refreshWith(ctx context.Context, load func(context.Context) ([]*pb.Product, error)) error {
	products, err := loadWithRetry(ctx, load)
	if err != nil {
		c.stale.Store(true)
		return err
	}
	c.store(products)
	return nil
}

// run primes the cache (retrying until the first success = latch), then refreshes
// every cacheRefreshInterval. It returns on ctx cancellation (shutdown).
func (c *productCache) run(ctx context.Context) {
	backoff := primeRetryInterval
	for !c.everPrimed.Load() {
		if err := c.refreshOnce(ctx); err != nil {
			if ctx.Err() != nil {
				return
			}
			logger.Warn(fmt.Sprintf("catalog cache: prime attempt failed, retrying in %s: %v", backoff, err))
			select {
			case <-ctx.Done():
				return
			case <-time.After(backoff):
			}
			if backoff < primeRetryMax {
				backoff *= 2
				if backoff > primeRetryMax {
					backoff = primeRetryMax
				}
			}
		}
	}
	if s := c.current(); s != nil {
		logger.Info(fmt.Sprintf("catalog cache primed: %d products (revision %s)", len(s.products), s.revision))
	}

	ticker := time.NewTicker(cacheRefreshInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := c.refreshOnce(ctx); err != nil && ctx.Err() == nil {
				logger.Warn(fmt.Sprintf("catalog cache: refresh failed, serving last-known-good: %v", err))
			}
		}
	}
}

// initCacheMetrics registers the freshness/reliability instruments (§3.1).
func initCacheMetrics(c *productCache) error {
	meter := otel.GetMeterProvider().Meter("product-catalog")

	var err error
	if servedStaleCounter, err = meter.Int64Counter("served_stale",
		metric.WithDescription("Customer reads served from stale last-known-good cache during a DB outage")); err != nil {
		return err
	}
	if dbRetryAttempts, err = meter.Int64Counter("db_retry_attempts",
		metric.WithDescription("Transient DB retry attempts on the catalog refresh path")); err != nil {
		return err
	}
	if dbRetryRecovered, err = meter.Int64Counter("db_retry_recovered",
		metric.WithDescription("Catalog refreshes that succeeded after at least one retry")); err != nil {
		return err
	}
	if dbRetryExhausted, err = meter.Int64Counter("db_retry_exhausted",
		metric.WithDescription("Catalog refreshes that failed after exhausting retries")); err != nil {
		return err
	}

	cachePrimed, err := meter.Int64ObservableGauge("cache_primed",
		metric.WithDescription("1 if the in-memory catalog snapshot is currently primed and schema-valid"))
	if err != nil {
		return err
	}
	everPrimed, err := meter.Int64ObservableGauge("ever_primed",
		metric.WithDescription("1 if the catalog cache has ever completed a full prime (readiness latch)"))
	if err != nil {
		return err
	}
	cacheAge, err := meter.Float64ObservableGauge("cache_age_seconds",
		metric.WithDescription("Seconds since the catalog snapshot was last successfully refreshed from the DB"))
	if err != nil {
		return err
	}

	cacheMetricsReg, err = meter.RegisterCallback(func(_ context.Context, o metric.Observer) error {
		var primed int64
		if c.schemaValid() {
			primed = 1
		}
		o.ObserveInt64(cachePrimed, primed)

		var ever int64
		if c.everPrimed.Load() {
			ever = 1
		}
		o.ObserveInt64(everPrimed, ever)

		if s := c.current(); s != nil {
			o.ObserveFloat64(cacheAge, time.Since(s.loadedAt).Seconds())
		} else {
			o.ObserveFloat64(cacheAge, 0)
		}
		return nil
	}, cachePrimed, everPrimed, cacheAge)
	return err
}

// runReadinessLatch drives the K8s gRPC readiness probe (the "" service) from the
// startup-latch state machine. It NEVER pings the DB: DB reachability is only a
// degraded signal, not a readiness input (§3.1). Liveness is a separate
// DB-independent tcpSocket probe, so a not-ready pod is not killed.
func runReadinessLatch(ctx context.Context, hc *health.Server, c *productCache) {
	apply := func() {
		st := healthpb.HealthCheckResponse_NOT_SERVING
		if c.ready() {
			st = healthpb.HealthCheckResponse_SERVING
		}
		hc.SetServingStatus("", st)
	}
	apply()

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			// Graceful drain: fail readiness so K8s removes the pod from
			// endpoints before the preStop sleep + GracefulStop.
			c.shutdown.Store(true)
			hc.SetServingStatus("", healthpb.HealthCheckResponse_NOT_SERVING)
			return
		case <-ticker.C:
			apply()
		}
	}
}

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGKILL)
	defer cancel()

	lp := initLoggerProvider()
	defer func() {
		if err := lp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Logger Provider Shutdown: %v", err))
		}
		logger.Info("Shutdown logger provider")
	}()

	tp := initTracerProvider()
	defer func() {
		if err := tp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Tracer Provider Shutdown: %v", err))
		}
		logger.Info("Shutdown tracer provider")
	}()

	mp := initMeterProvider()
	defer func() {
		if err := mp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down meter provider: %v", err))
		}
		logger.Info("Shutdown meter provider")
	}()

	// M9-01: open the DB handle but do NOT block on reachability. If the DB is
	// down at startup the pod still comes up, stays NOT_SERVING (startup latch),
	// and primes once the DB is reachable — no crash-loop.
	if err := initDatabase(); err != nil {
		logger.Error(fmt.Sprintf("Error initializing database: %v", err))
		os.Exit(1)
	}
	defer func() {
		if db != nil {
			if err := db.Close(); err != nil {
				logger.Error(fmt.Sprintf("Error closing database connection: %v", err))
			} else {
				logger.Info("Database connection closed")
			}
		}
		if reg != nil {
			if err := reg.Unregister(); err != nil {
				logger.Error(fmt.Sprintf("Error unregistering database metrics: %v", err))
			} else {
				logger.Info("Database metrics unregistered")
			}
		}
		if cacheMetricsReg != nil {
			if err := cacheMetricsReg.Unregister(); err != nil {
				logger.Error(fmt.Sprintf("Error unregistering cache metrics: %v", err))
			}
		}
	}()

	// Build the cache and start the prime/refresh loop before serving. The pod
	// stays NOT_SERVING until this loop completes the first full prime.
	catalogCache = newProductCache()
	if err := initCacheMetrics(catalogCache); err != nil {
		logger.Error(fmt.Sprintf("Error initializing cache metrics: %v", err))
	}
	go catalogCache.run(ctx)

	openfeature.AddHooks(otelhooks.NewTracesHook())
	provider, err := flagd.NewProvider()
	if err != nil {
		logger.Error(err.Error())
	}
	err = openfeature.SetProvider(provider)
	if err != nil {
		logger.Error(err.Error())
	}

	err = runtime.Start(runtime.WithMinimumReadMemStatsInterval(time.Second))
	if err != nil {
		logger.Error(err.Error())
	}

	svc := &productCatalog{}
	var port string
	mustMapEnv(&port, "PRODUCT_CATALOG_PORT")

	logger.Info(fmt.Sprintf("Product Catalog gRPC server started on port: %s", port))

	ln, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		logger.Error(fmt.Sprintf("TCP Listen: %v", err))
	}

	srv := grpc.NewServer(
		grpc.StatsHandler(otelgrpc.NewServerHandler()),
	)

	reflection.Register(srv)

	pb.RegisterProductCatalogServiceServer(srv, svc)

	healthcheck := health.NewServer()
	healthpb.RegisterHealthServer(srv, healthcheck)

	// M9-01 (§3.1) startup latch: grpc's health.NewServer() defaults the ""
	// service to SERVING. Force NOT_SERVING BEFORE we start serving so the very
	// first readiness probe cannot see a "ready" pod with an empty cache. The
	// readiness goroutine flips it to SERVING only after the cache has primed.
	healthcheck.SetServingStatus("", healthpb.HealthCheckResponse_NOT_SERVING)
	go runReadinessLatch(ctx, healthcheck, catalogCache)

	go func() {
		if err := srv.Serve(ln); err != nil {
			logger.Error(fmt.Sprintf("Failed to serve gRPC server, err: %v", err))
		}
	}()

	<-ctx.Done()

	// Signal graceful drain immediately (readiness goroutine also handles this on
	// ctx.Done); then let in-flight RPCs finish.
	catalogCache.shutdown.Store(true)
	healthcheck.SetServingStatus("", healthpb.HealthCheckResponse_NOT_SERVING)
	srv.GracefulStop()
	logger.Info("Product Catalog gRPC server stopped")
}

// loadProductsFromDB loads the entire catalog. It is the snapshot source for the
// prime/refresh loop — NOT called on the customer request path.
func loadProductsFromDB(ctx context.Context) ([]*pb.Product, error) {
	if db == nil {
		return nil, fmt.Errorf("database connection not initialized")
	}

	// Query all products with categories
	rows, err := db.QueryContext(ctx, `
		SELECT p.id, p.name, p.description, p.picture,
		       p.price_currency_code, p.price_units, p.price_nanos, p.categories
		FROM catalog.products p
		ORDER BY p.id
	`)
	if err != nil {
		return nil, fmt.Errorf("failed to query products: %w", err)
	}
	defer rows.Close()

	products, err := getProductsFromRows(ctx, rows)
	if err != nil {
		return nil, fmt.Errorf("failed to get products from rows: %w", err)
	}

	return products, nil
}

func getProductsFromRows(ctx context.Context, rows *sql.Rows) ([]*pb.Product, error) {
	var products []*pb.Product

	for rows.Next() {
		var id, name, description, picture, currencyCode, categoriesStr string
		var units int64
		var nanos int32

		if err := rows.Scan(&id, &name, &description, &picture, &currencyCode, &units, &nanos, &categoriesStr); err != nil {
			return nil, fmt.Errorf("failed to scan product row: %w", err)
		}

		products = append(products, parseProductRow(id, name, description, picture, currencyCode, categoriesStr, units, nanos))
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("error iterating product rows: %w", err)
	}

	logger.LogAttrs(
		ctx,
		slog.LevelInfo,
		fmt.Sprintf("Found %d products from database", len(products)),
		slog.Int("products", len(products)),
	)

	return products, nil
}

func parseProductRow(id, name, description, picture, currencyCode, categoriesStr string, units int64, nanos int32) *pb.Product {
	// Parse comma-delimited categories string into slice
	var categories []string
	if categoriesStr != "" {
		categories = strings.Split(categoriesStr, ",")
		// Trim whitespace from each category
		for i, cat := range categories {
			categories[i] = strings.TrimSpace(cat)
		}
	}

	return &pb.Product{
		Id:          id,
		Name:        name,
		Description: description,
		Picture:     picture,
		PriceUsd: &pb.Money{
			CurrencyCode: currencyCode,
			Units:        units,
			Nanos:        nanos,
		},
		Categories: categories,
	}
}

func mustMapEnv(target *string, key string) {
	value, present := os.LookupEnv(key)
	if !present {
		logger.Error(fmt.Sprintf("Environment Variable Not Set: %q", key))
	}
	*target = value
}

func (p *productCatalog) Check(ctx context.Context, req *healthpb.HealthCheckRequest) (*healthpb.HealthCheckResponse, error) {
	return &healthpb.HealthCheckResponse{Status: healthpb.HealthCheckResponse_SERVING}, nil
}

func (p *productCatalog) Watch(req *healthpb.HealthCheckRequest, ws healthpb.Health_WatchServer) error {
	return status.Errorf(codes.Unimplemented, "health check via Watch not implemented")
}

func (p *productCatalog) ListProducts(ctx context.Context, req *pb.Empty) (*pb.ListProductsResponse, error) {
	span := trace.SpanFromContext(ctx)

	products, err := catalogCache.list()
	if err != nil {
		span.SetStatus(otelcodes.Error, err.Error())
		return nil, status.Errorf(codes.Unavailable, "catalog cache not ready: %v", err)
	}
	recordServedStale(ctx, "ListProducts")

	span.SetAttributes(
		attribute.Int("app.products.count", len(products)),
	)
	return &pb.ListProductsResponse{Products: products}, nil
}

func (p *productCatalog) GetProduct(ctx context.Context, req *pb.GetProductRequest) (*pb.Product, error) {
	span := trace.SpanFromContext(ctx)
	span.SetAttributes(
		attribute.String("app.product.id", req.Id),
	)

	// GetProduct will fail on a specific product when feature flag is enabled
	if p.checkProductFailure(ctx, req.Id) {
		msg := "Error: Product Catalog Fail Feature Flag Enabled"
		span.SetStatus(otelcodes.Error, msg)
		span.AddEvent(msg)
		return nil, status.Error(codes.Internal, msg)
	}

	found, ok, err := catalogCache.get(req.Id)
	if err != nil {
		span.SetStatus(otelcodes.Error, err.Error())
		return nil, status.Errorf(codes.Unavailable, "catalog cache not ready: %v", err)
	}
	if !ok {
		msg := fmt.Sprintf("Product Not Found: %s", req.Id)
		span.SetStatus(otelcodes.Error, msg)
		span.AddEvent(msg)
		return nil, status.Error(codes.NotFound, msg)
	}
	recordServedStale(ctx, "GetProduct")

	span.AddEvent("Product Found")
	span.SetAttributes(
		attribute.String("app.product.id", req.Id),
		attribute.String("app.product.name", found.Name),
	)

	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "Product Found",
		slog.String("app.product.name", found.Name),
		slog.String("app.product.id", req.Id),
	)

	return found, nil
}

func (p *productCatalog) SearchProducts(ctx context.Context, req *pb.SearchProductsRequest) (*pb.SearchProductsResponse, error) {
	span := trace.SpanFromContext(ctx)

	result, err := catalogCache.search(req.Query)
	if err != nil {
		span.SetStatus(otelcodes.Error, err.Error())
		return nil, status.Errorf(codes.Unavailable, "catalog cache not ready: %v", err)
	}
	recordServedStale(ctx, "SearchProducts")

	span.SetAttributes(
		attribute.Int("app.products_search.count", len(result)),
	)
	return &pb.SearchProductsResponse{Results: result}, nil
}

func (p *productCatalog) checkProductFailure(ctx context.Context, id string) bool {
	if id != "OLJCESPC7Z" {
		return false
	}

	client := openfeature.NewClient("productCatalog")
	failureEnabled, _ := client.BooleanValue(
		ctx, "productCatalogFailure", false, openfeature.EvaluationContext{},
	)
	return failureEnabled
}
