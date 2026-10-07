import time
import statistics
import math

def compute_task():
    # 1. Prímszámok keresése (Eratoszthenészi szita)
    limit = 10000
    sieve = [True] * (limit + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(limit**0.5) + 1):
        if sieve[i]:
            for j in range(i*i, limit + 1, i):
                sieve[j] = False
    primes = [i for i, is_prime in enumerate(sieve) if is_prime]

    # 2. Mátrix szorzás / 2D listák feldolgozása (30x30)
    n = 30
    a = [[(i + j) % 10 for j in range(n)] for i in range(n)]
    b = [[(i * j) % 10 for j in range(n)] for i in range(n)]
    result_matrix = [[sum(a[i][k] * b[k][j] for k in range(n)) for j in range(n)] for i in range(n)]

    # 3. Lista rendezés és szövegmanipuláció
    words = [f"word_{i}_{math.sin(i):.4f}" for i in range(5000)]
    sorted_words = sorted(words, key=lambda x: (len(x), x[::-1]))

    return len(primes), len(result_matrix), len(sorted_words)

def main():
    iterations = 50
    execution_times = []

    print(f"=== Benchmark indítása ({iterations} futás) ===")
    
    # Bemelegítő (warmup) futás
    compute_task()

    for i in range(1, iterations + 1):
        start_time = time.perf_counter()
        compute_task()
        end_time = time.perf_counter()
        
        elapsed_ms = (end_time - start_time) * 1000
        execution_times.append(elapsed_ms)
        
        # Minden 10. futásnál státusz kiírás
        if i % 10 == 0 or i == 1:
            print(f"[{i:02d}/{iterations}] Futási idő: {elapsed_ms:.2f} ms")

    total_time_ms = sum(execution_times)
    avg_time = statistics.mean(execution_times)
    median_time = statistics.median(execution_times)
    min_time = min(execution_times)
    max_time = max(execution_times)
    std_dev = statistics.stdev(execution_times) if len(execution_times) > 1 else 0.0

    print("\n" + "=" * 45)
    print("           BENCHMARK EREDMÉNYEK           ")
    print("=" * 45)
    print(f"Összes futtatás:   {iterations} alkalom")
    print(f"Teljes időtartam:  {total_time_ms:.2f} ms ({total_time_ms / 1000:.3f} s)")
    print(f"Átlagos sebesség:  {avg_time:.2f} ms")
    print(f"Medián sebesség:   {median_time:.2f} ms")
    print(f"Leggyorsabb futás: {min_time:.2f} ms")
    print(f"Leglassabb futás:  {max_time:.2f} ms")
    print(f"Szórás (std dev):  {std_dev:.2f} ms")
    print("=" * 45)

if __name__ == "__main__":
    main()
