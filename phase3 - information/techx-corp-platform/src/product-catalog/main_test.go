// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
//
// Unit tests for M9-01: canonical in-memory snapshot (list/get/search),
// startup-latch readiness state machine, transient blip retry, and the
// keep-last-known-good refresh behaviour.
package main

import (
	"context"
	"database/sql/driver"
	"errors"
	"fmt"
	"net"
	"testing"
	"time"

	"github.com/lib/pq"
	pb "github.com/opentelemetry/techx-corp/src/product-catalog/genproto/oteldemo"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"go.opentelemetry.io/otel"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

func fixtureProducts() []*pb.Product {
	// Deliberately provided in id order (as the snapshot source query returns).
	return []*pb.Product{
		{Id: "A1", Name: "Red Bicycle", Description: "A fast road bike", Categories: []string{"cycling"}},
		{Id: "B2", Name: "Blue Kayak", Description: "Stable touring KAYAK", Categories: []string{"water", "sports"}},
		{Id: "C3", Name: "Green Tent", Description: "Waterproof 2-person tent", Categories: []string{"camping"}},
	}
}

func primedCache(t *testing.T) *productCache {
	t.Helper()
	c := newProductCache()
	c.store(fixtureProducts())
	return c
}

// ---- snapshot: list / get / search ----------------------------------------

func TestCacheList(t *testing.T) {
	c := primedCache(t)
	got, err := c.list()
	if err != nil {
		t.Fatalf("list: unexpected error: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("list: want 3 products, got %d", len(got))
	}
	// order preserved (id-sorted source)
	if got[0].Id != "A1" || got[1].Id != "B2" || got[2].Id != "C3" {
		t.Fatalf("list: order not preserved: %v", []string{got[0].Id, got[1].Id, got[2].Id})
	}
}

func TestCacheGet(t *testing.T) {
	c := primedCache(t)

	p, ok, err := c.get("B2")
	if err != nil {
		t.Fatalf("get: unexpected error: %v", err)
	}
	if !ok || p.Name != "Blue Kayak" {
		t.Fatalf("get(B2): want Blue Kayak, ok=true; got %v ok=%v", p, ok)
	}

	_, ok, err = c.get("NOPE")
	if err != nil {
		t.Fatalf("get(missing): unexpected error: %v", err)
	}
	if ok {
		t.Fatalf("get(missing): want ok=false")
	}
}

func TestCacheSearch(t *testing.T) {
	c := primedCache(t)

	cases := []struct {
		name    string
		query   string
		wantIDs []string
	}{
		{"case-insensitive name", "bicycle", []string{"A1"}},
		{"uppercase query matches lowercase name", "BICYCLE", []string{"A1"}},
		{"matches description", "waterproof", []string{"C3"}},
		{"description case-insensitive", "kayak", []string{"B2"}}, // desc has "KAYAK", name has "Kayak"
		{"substring across multiple", "e", []string{"A1", "B2", "C3"}},
		{"empty query matches all", "", []string{"A1", "B2", "C3"}},
		{"no match", "zzzzz", nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := c.search(tc.query)
			if err != nil {
				t.Fatalf("search(%q): unexpected error: %v", tc.query, err)
			}
			gotIDs := make([]string, len(got))
			for i, p := range got {
				gotIDs[i] = p.Id
			}
			if fmt.Sprint(gotIDs) != fmt.Sprint(tc.wantIDs) {
				t.Fatalf("search(%q): want %v, got %v", tc.query, tc.wantIDs, gotIDs)
			}
		})
	}
}

func TestEmptyCatalogSnapshot(t *testing.T) {
	// A valid prime of an empty catalog: everything works, no panics.
	c := newProductCache()
	c.store([]*pb.Product{})

	if !c.ready() {
		t.Fatalf("empty-but-primed cache should be ready")
	}
	if got, _ := c.list(); len(got) != 0 {
		t.Fatalf("list on empty catalog: want 0, got %d", len(got))
	}
	if _, ok, _ := c.get("A1"); ok {
		t.Fatalf("get on empty catalog: want ok=false")
	}
	if got, _ := c.search("anything"); len(got) != 0 {
		t.Fatalf("search on empty catalog: want 0, got %d", len(got))
	}
}

func TestReadsBeforePrimeAreUnavailable(t *testing.T) {
	c := newProductCache() // never primed: snap == nil
	if _, err := c.list(); !errors.Is(err, errCacheNotPrimed) {
		t.Fatalf("list before prime: want errCacheNotPrimed, got %v", err)
	}
	if _, _, err := c.get("A1"); !errors.Is(err, errCacheNotPrimed) {
		t.Fatalf("get before prime: want errCacheNotPrimed, got %v", err)
	}
	if _, err := c.search("x"); !errors.Is(err, errCacheNotPrimed) {
		t.Fatalf("search before prime: want errCacheNotPrimed, got %v", err)
	}
}

// ---- startup-latch state machine ------------------------------------------

func TestReadinessStartupLatch(t *testing.T) {
	c := newProductCache()

	// STARTUP: not ready even though nothing is wrong — cache not primed yet.
	if c.everPrimed.Load() {
		t.Fatalf("fresh cache should not have ever_primed set")
	}
	if c.ready() {
		t.Fatalf("STARTUP: cache must NOT be ready before first prime (latch)")
	}
	if c.schemaValid() {
		t.Fatalf("STARTUP: schemaValid should be false with no snapshot")
	}

	// Prime -> latch fires, becomes ready.
	c.store(fixtureProducts())
	if !c.everPrimed.Load() {
		t.Fatalf("after prime: ever_primed must be set")
	}
	if !c.ready() {
		t.Fatalf("STEADY: primed cache must be ready")
	}

	// STEADY: a later refresh failure keeps ready=true (DB is only a degraded signal).
	c.stale.Store(true)
	if !c.ready() {
		t.Fatalf("STEADY: stale cache must stay ready (DB down != not ready)")
	}

	// SHUTDOWN: graceful drain fails readiness.
	c.shutdown.Store(true)
	if c.ready() {
		t.Fatalf("SHUTDOWN: must not be ready during graceful drain")
	}
}

func TestReadinessSchemaMismatch(t *testing.T) {
	c := newProductCache() // expects revision cacheSchemaRevision
	// Simulate a snapshot built under a different (old) schema revision.
	c.snap.Store(&productSnapshot{
		revision: "OLD-SCHEMA",
		products: fixtureProducts(),
		loadedAt: time.Now(),
	})
	c.everPrimed.Store(true) // latch fired, but schema doesn't match

	if c.schemaValid() {
		t.Fatalf("schema mismatch must be invalid")
	}
	if c.ready() {
		t.Fatalf("schema mismatch must NOT be ready even when ever_primed=true")
	}
}

// ---- transient blip retry --------------------------------------------------

func TestIsTransientDBError(t *testing.T) {
	transient := []error{
		driver.ErrBadConn,
		&net.OpError{Op: "dial", Err: errors.New("connection refused")},
		&pq.Error{Code: "57P03"}, // cannot_connect_now
		&pq.Error{Code: "57P01"}, // admin_shutdown
		&pq.Error{Code: "08006"}, // connection_failure
		fmt.Errorf("driver: %w", driver.ErrBadConn),
		errors.New("write: broken pipe"),
		errors.New("read tcp 10.0.0.1:5432: i/o timeout"),
	}
	for _, err := range transient {
		if !isTransientDBError(err) {
			t.Errorf("want transient=true for %v", err)
		}
	}

	permanent := []error{
		nil,
		errors.New("permission denied for table products"),
		&pq.Error{Code: "42P01"}, // undefined_table
		&pq.Error{Code: "23505"}, // unique_violation
		context.Canceled,
	}
	for _, err := range permanent {
		if isTransientDBError(err) {
			t.Errorf("want transient=false for %v", err)
		}
	}
}

func TestLoadWithRetryRecoversWithinBudget(t *testing.T) {
	defer withFastBackoffs(t)()

	var calls int
	load := func(ctx context.Context) ([]*pb.Product, error) {
		calls++
		if calls < 3 { // fail twice, succeed on the 3rd attempt
			return nil, driver.ErrBadConn
		}
		return fixtureProducts(), nil
	}

	got, err := loadWithRetry(context.Background(), load)
	if err != nil {
		t.Fatalf("expected recovery, got error: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("expected 3 products after recovery, got %d", len(got))
	}
	if calls != 3 {
		t.Fatalf("expected exactly 3 attempts, got %d", calls)
	}
}

func TestLoadWithRetryExhausts(t *testing.T) {
	defer withFastBackoffs(t)()

	var calls int
	load := func(ctx context.Context) ([]*pb.Product, error) {
		calls++
		return nil, driver.ErrBadConn
	}

	_, err := loadWithRetry(context.Background(), load)
	if err == nil {
		t.Fatalf("expected error after exhausting retries")
	}
	if calls != 4 { // 1 initial + 3 retries
		t.Fatalf("expected 4 attempts (4 tries total), got %d", calls)
	}
}

func TestLoadWithRetryStopsOnPermanentError(t *testing.T) {
	defer withFastBackoffs(t)()

	permanent := errors.New("permission denied for table products")
	var calls int
	load := func(ctx context.Context) ([]*pb.Product, error) {
		calls++
		return nil, permanent
	}

	_, err := loadWithRetry(context.Background(), load)
	if !errors.Is(err, permanent) {
		t.Fatalf("expected the permanent error back, got %v", err)
	}
	if calls != 1 {
		t.Fatalf("permanent error must not retry; expected 1 attempt, got %d", calls)
	}
}

func TestRetryBudgetIs700ms(t *testing.T) {
	// The mandate pins the blip budget: 4 attempts, 100/200/400ms = 700ms total.
	if len(retryBackoffs) != 3 {
		t.Fatalf("want 3 backoffs (4 attempts total), got %d", len(retryBackoffs))
	}
	var total time.Duration
	for _, d := range retryBackoffs {
		total += d
	}
	if total != 700*time.Millisecond {
		t.Fatalf("want 700ms total backoff, got %v", total)
	}
}

// ---- refresh keeps last-known-good ----------------------------------------

func TestRefreshFailureKeepsLastKnownGood(t *testing.T) {
	defer withFastBackoffs(t)()
	c := newProductCache()

	// First refresh succeeds -> primed, fresh.
	okLoad := func(ctx context.Context) ([]*pb.Product, error) { return fixtureProducts(), nil }
	if err := c.refreshWith(context.Background(), okLoad); err != nil {
		t.Fatalf("initial refresh: %v", err)
	}
	if c.stale.Load() {
		t.Fatalf("after successful refresh: stale must be false")
	}
	firstSnap := c.current()

	// Subsequent refresh fails (DB outage) -> stale=true, snapshot UNCHANGED.
	failLoad := func(ctx context.Context) ([]*pb.Product, error) { return nil, driver.ErrBadConn }
	if err := c.refreshWith(context.Background(), failLoad); err == nil {
		t.Fatalf("expected refresh failure")
	}
	if !c.stale.Load() {
		t.Fatalf("after failed refresh: stale must be true")
	}
	if c.current() != firstSnap {
		t.Fatalf("failed refresh must keep the exact last-known-good snapshot")
	}
	// Still ready (latch) and still serving the good data.
	if !c.ready() {
		t.Fatalf("cache must stay ready during a refresh outage")
	}
	got, err := c.list()
	if err != nil || len(got) != 3 {
		t.Fatalf("must keep serving last-known-good: got %d products, err=%v", len(got), err)
	}

	// Recovery: next successful refresh clears stale and swaps a new snapshot.
	if err := c.refreshWith(context.Background(), okLoad); err != nil {
		t.Fatalf("recovery refresh: %v", err)
	}
	if c.stale.Load() {
		t.Fatalf("after recovery: stale must be false")
	}
	if c.current() == firstSnap {
		t.Fatalf("recovery should have swapped in a new snapshot")
	}
}

// ---- gRPC handlers over the cache -----------------------------------------

func TestListProductsHandler(t *testing.T) {
	withGlobalCache(t, primedCache(t))
	svc := &productCatalog{}

	resp, err := svc.ListProducts(context.Background(), &pb.Empty{})
	if err != nil {
		t.Fatalf("ListProducts: %v", err)
	}
	if len(resp.Products) != 3 {
		t.Fatalf("ListProducts: want 3, got %d", len(resp.Products))
	}
}

func TestGetProductHandler(t *testing.T) {
	withGlobalCache(t, primedCache(t))
	svc := &productCatalog{}

	// existing
	p, err := svc.GetProduct(context.Background(), &pb.GetProductRequest{Id: "A1"})
	if err != nil {
		t.Fatalf("GetProduct(A1): %v", err)
	}
	if p.Name != "Red Bicycle" {
		t.Fatalf("GetProduct(A1): want Red Bicycle, got %q", p.Name)
	}

	// missing -> NotFound
	_, err = svc.GetProduct(context.Background(), &pb.GetProductRequest{Id: "NOPE"})
	if status.Code(err) != codes.NotFound {
		t.Fatalf("GetProduct(missing): want NotFound, got %v", err)
	}
}

func TestSearchProductsHandler(t *testing.T) {
	withGlobalCache(t, primedCache(t))
	svc := &productCatalog{}

	resp, err := svc.SearchProducts(context.Background(), &pb.SearchProductsRequest{Query: "tent"})
	if err != nil {
		t.Fatalf("SearchProducts: %v", err)
	}
	if len(resp.Results) != 1 || resp.Results[0].Id != "C3" {
		t.Fatalf("SearchProducts(tent): want [C3], got %v", resp.Results)
	}
}

func TestHandlerUnavailableBeforePrime(t *testing.T) {
	withGlobalCache(t, newProductCache()) // never primed
	svc := &productCatalog{}

	_, err := svc.ListProducts(context.Background(), &pb.Empty{})
	if status.Code(err) != codes.Unavailable {
		t.Fatalf("ListProducts before prime: want Unavailable, got %v", err)
	}
}

// ---- metrics wiring --------------------------------------------------------

func TestMetricsInstrumentsAndServedStale(t *testing.T) {
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	prevMP := otel.GetMeterProvider()
	otel.SetMeterProvider(mp)
	t.Cleanup(func() { otel.SetMeterProvider(prevMP); _ = mp.Shutdown(context.Background()) })

	defer withFastBackoffs(t)()

	c := primedCache(t)
	withGlobalCache(t, c)
	if err := initCacheMetrics(c); err != nil {
		t.Fatalf("initCacheMetrics: %v", err)
	}
	t.Cleanup(func() {
		if cacheMetricsReg != nil {
			_ = cacheMetricsReg.Unregister()
		}
	})

	// Simulate an outage: cache stale -> a customer read records served_stale.
	c.stale.Store(true)
	recordServedStale(context.Background(), "ListProducts")
	recordServedStale(context.Background(), "SearchProducts")

	// Exercise the retry counters so they emit (sync counters with no
	// measurement are not collected). failThenOK: 2 retries then recover.
	var n int
	failThenOK := func(ctx context.Context) ([]*pb.Product, error) {
		n++
		if n < 3 {
			return nil, driver.ErrBadConn
		}
		return fixtureProducts(), nil
	}
	if _, err := loadWithRetry(context.Background(), failThenOK); err != nil {
		t.Fatalf("failThenOK should recover: %v", err)
	}
	alwaysFail := func(ctx context.Context) ([]*pb.Product, error) { return nil, driver.ErrBadConn }
	if _, err := loadWithRetry(context.Background(), alwaysFail); err == nil {
		t.Fatalf("alwaysFail should exhaust")
	}

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("collect: %v", err)
	}

	names := collectedMetricNames(rm)
	for _, want := range []string{
		"cache_primed", "ever_primed", "cache_age_seconds",
		"served_stale", "db_retry_attempts", "db_retry_recovered", "db_retry_exhausted",
	} {
		if !names[want] {
			t.Errorf("expected metric %q to be registered; got %v", want, keys(names))
		}
	}

	if got := sumInt64Counter(rm, "served_stale"); got != 2 {
		t.Fatalf("served_stale: want 2, got %d", got)
	}
	// failThenOK: 2 retry attempts + 1 recovered. alwaysFail: 3 retry attempts + 1 exhausted.
	if got := sumInt64Counter(rm, "db_retry_attempts"); got != 5 {
		t.Fatalf("db_retry_attempts: want 5, got %d", got)
	}
	if got := sumInt64Counter(rm, "db_retry_recovered"); got != 1 {
		t.Fatalf("db_retry_recovered: want 1, got %d", got)
	}
	if got := sumInt64Counter(rm, "db_retry_exhausted"); got != 1 {
		t.Fatalf("db_retry_exhausted: want 1, got %d", got)
	}
	if got := gaugeInt64(rm, "ever_primed"); got != 1 {
		t.Fatalf("ever_primed gauge: want 1, got %d", got)
	}
	if got := gaugeInt64(rm, "cache_primed"); got != 1 {
		t.Fatalf("cache_primed gauge: want 1, got %d", got)
	}
}

// ---- test helpers ----------------------------------------------------------

// withFastBackoffs shrinks the retry backoffs so timing tests run fast, and
// restores them afterwards.
func withFastBackoffs(t *testing.T) func() {
	t.Helper()
	orig := retryBackoffs
	retryBackoffs = []time.Duration{time.Millisecond, time.Millisecond, time.Millisecond}
	return func() { retryBackoffs = orig }
}

// withGlobalCache sets the package-level catalogCache for handler tests and
// restores the previous value afterwards.
func withGlobalCache(t *testing.T, c *productCache) {
	t.Helper()
	prev := catalogCache
	catalogCache = c
	t.Cleanup(func() { catalogCache = prev })
}

func collectedMetricNames(rm metricdata.ResourceMetrics) map[string]bool {
	names := map[string]bool{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			names[m.Name] = true
		}
	}
	return names
}

func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

func sumInt64Counter(rm metricdata.ResourceMetrics, name string) int64 {
	var total int64
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if m.Name != name {
				continue
			}
			if sum, ok := m.Data.(metricdata.Sum[int64]); ok {
				for _, dp := range sum.DataPoints {
					total += dp.Value
				}
			}
		}
	}
	return total
}

func gaugeInt64(rm metricdata.ResourceMetrics, name string) int64 {
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if m.Name != name {
				continue
			}
			if g, ok := m.Data.(metricdata.Gauge[int64]); ok {
				for _, dp := range g.DataPoints {
					return dp.Value
				}
			}
		}
	}
	return -1
}
