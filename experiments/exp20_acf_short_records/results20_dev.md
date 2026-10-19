# exp20 dev report (synthetic short records)

Seeds: dev 0..99

## Summary

| candidate | F pass | worst negative cell | pooled neg | S pool | L share | c3-4 share | snr0.5 share | chosen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | no | neg ar050 n=3000 (11.0%) | 0.9% | 50.9% | 86.2% | 0.0% | 18.1% |  |
| B | no | neg ar090 n=1000 (30.0%) | 9.7% | 95.6% | 92.9% | 0.3% | 46.5% |  |
| C | no | neg ar050 n=1000 (14.0%) | 2.2% | 83.4% | 86.2% | 1.5% | 35.3% |  |
| D | no | neg ar090 n=1000 (22.0%) | 6.0% | 91.1% | 86.0% | 52.9% | 52.6% |  |
| E | no | neg ar050 n=1000 (14.0%) | 2.3% | 81.8% | 87.9% | 0.0% | 32.6% |  |

Winner: **none**

## Reason counts (positives)

- A: too few ACF zero crossings: 25892, regular: 11435, irregular (r=0.94): 11, irregular (r=0.88): 13, irregular (r=0.98): 4, irregular (r=0.89): 11, irregular (r=0.86): 12, irregular (r=0.64): 7, irregular (r=0.80): 7, irregular (r=0.95): 15, irregular (r=0.99): 6, irregular (r=0.42): 7, irregular (r=0.63): 18, irregular (r=0.33): 4, irregular (r=0.66): 2, irregular (r=0.97): 8, irregular (r=0.84): 10, irregular (r=0.56): 5, irregular (r=0.93): 13, irregular (r=0.75): 6, irregular (r=0.51): 3, irregular (r=0.32): 3, irregular (r=0.61): 10, irregular (r=0.78): 7, irregular (r=0.54): 9, irregular (r=0.43): 3, irregular (r=0.48): 2, irregular (r=0.45): 11, irregular (r=0.62): 6, irregular (r=0.67): 8, irregular (r=0.77): 6, irregular (r=0.87): 15, irregular (r=0.76): 10, irregular (r=0.91): 5, irregular (r=0.39): 7, irregular (r=0.50): 10, irregular (r=0.96): 6, irregular (r=0.83): 11, irregular (r=0.35): 9, irregular (r=0.31): 5, irregular (r=0.71): 5, irregular (r=0.72): 3, irregular (r=0.85): 11, irregular (r=0.82): 6, irregular (r=0.57): 9, irregular (r=0.41): 7, irregular (r=0.52): 7, irregular (r=0.46): 4, irregular (r=0.79): 9, irregular (r=0.47): 4, irregular (r=0.90): 12, irregular (r=0.44): 7, irregular (r=0.70): 4, irregular (r=0.34): 1, irregular (r=0.81): 6, irregular (r=0.92): 10, irregular (r=0.69): 4, irregular (r=0.68): 6, irregular (r=0.58): 5, irregular (r=0.73): 2, irregular (r=0.59): 5, irregular (r=0.49): 7, irregular (r=0.40): 4, irregular (r=0.60): 10, irregular (r=0.53): 3, irregular (r=0.38): 2, irregular (r=0.65): 3, irregular (r=0.55): 5, irregular (r=0.37): 2, irregular (r=0.28): 1, irregular (r=0.36): 2, irregular (r=0.74): 1, irregular (r=0.30): 1
- B: too few ACF zero crossings: 12187, irregular (r=0.65): 37, irregular (r=0.42): 40, regular: 23091, irregular (r=0.70): 46, irregular (r=0.78): 32, irregular (r=0.73): 53, irregular (r=0.77): 40, irregular (r=0.94): 22, irregular (r=0.61): 57, irregular (r=0.67): 44, irregular (r=0.74): 42, irregular (r=0.92): 23, irregular (r=0.83): 38, irregular (r=0.88): 37, irregular (r=0.96): 21, irregular (r=0.97): 20, irregular (r=0.89): 32, irregular (r=0.75): 46, irregular (r=0.86): 43, irregular (r=0.80): 55, irregular (r=0.52): 50, irregular (r=0.82): 42, irregular (r=0.39): 27, irregular (r=0.95): 21, irregular (r=0.85): 38, irregular (r=0.58): 52, irregular (r=0.31): 3, irregular (r=0.66): 41, irregular (r=0.55): 57, irregular (r=0.54): 54, irregular (r=0.84): 33, irregular (r=0.98): 18, irregular (r=0.49): 50, irregular (r=0.56): 57, irregular (r=0.71): 36, irregular (r=0.62): 43, irregular (r=0.93): 30, irregular (r=0.35): 30, irregular (r=0.51): 48, irregular (r=0.48): 44, irregular (r=0.38): 18, irregular (r=0.81): 36, irregular (r=0.45): 33, irregular (r=0.37): 22, irregular (r=0.57): 63, irregular (r=0.76): 45, irregular (r=0.32): 5, irregular (r=0.50): 65, irregular (r=0.59): 57, irregular (r=0.41): 22, irregular (r=0.43): 31, irregular (r=0.44): 30, irregular (r=0.46): 31, irregular (r=0.68): 40, irregular (r=0.72): 44, irregular (r=0.64): 41, irregular (r=0.99): 24, irregular (r=0.87): 35, irregular (r=0.91): 25, irregular (r=0.90): 24, irregular (r=0.63): 43, irregular (r=0.79): 29, irregular (r=0.60): 46, irregular (r=0.40): 21, irregular (r=0.36): 17, irregular (r=0.53): 53, irregular (r=0.69): 45, irregular (r=0.30): 7, irregular (r=0.47): 35, irregular (r=0.33): 7, irregular (r=1.00): 9, irregular (r=0.34): 15, irregular (r=0.27): 1, irregular (r=0.28): 1
- C: too few ACF zero crossings: 17136, irregular (r=0.65): 9, regular: 19567, irregular (r=0.70): 12, irregular (r=0.94): 19, irregular (r=0.90): 24, irregular (r=0.81): 14, irregular (r=0.64): 15, irregular (r=0.75): 10, irregular (r=0.77): 13, irregular (r=0.66): 11, irregular (r=0.88): 36, irregular (r=0.41): 13, irregular (r=0.74): 16, irregular (r=0.53): 11, irregular (r=0.51): 12, irregular (r=0.60): 16, irregular (r=0.72): 6, irregular (r=0.86): 22, irregular (r=0.97): 16, irregular (r=0.92): 31, irregular (r=0.91): 23, irregular (r=0.67): 13, irregular (r=0.98): 12, irregular (r=0.83): 29, irregular (r=0.93): 28, irregular (r=0.82): 18, irregular (r=0.89): 25, irregular (r=0.73): 14, irregular (r=0.55): 21, irregular (r=0.80): 11, irregular (r=0.85): 26, irregular (r=0.78): 13, irregular (r=0.43): 15, irregular (r=0.29): 12, irregular (r=0.34): 10, irregular (r=0.25): 6, irregular (r=0.26): 6, irregular (r=0.95): 16, irregular (r=0.99): 25, irregular (r=0.42): 13, irregular (r=0.31): 15, irregular (r=0.28): 12, irregular (r=0.33): 16, irregular (r=0.38): 13, irregular (r=0.54): 14, irregular (r=0.84): 18, irregular (r=0.57): 18, irregular (r=0.56): 7, irregular (r=0.32): 6, irregular (r=0.35): 12, irregular (r=0.61): 16, irregular (r=0.48): 6, irregular (r=0.39): 10, irregular (r=0.45): 12, irregular (r=0.50): 19, irregular (r=0.69): 7, irregular (r=0.96): 13, irregular (r=0.87): 28, irregular (r=0.49): 11, irregular (r=0.27): 8, irregular (r=0.76): 19, irregular (r=0.63): 26, irregular (r=0.68): 17, irregular (r=0.58): 11, irregular (r=0.71): 8, irregular (r=0.36): 9, irregular (r=0.79): 18, irregular (r=0.23): 2, irregular (r=0.52): 13, irregular (r=0.46): 10, irregular (r=0.37): 4, irregular (r=0.62): 9, irregular (r=0.47): 6, irregular (r=0.44): 11, irregular (r=0.59): 14, irregular (r=0.40): 9, irregular (r=0.30): 6, irregular (r=1.00): 1, irregular (r=0.24): 1
- D: too few ACF zero crossings: 7275, regular: 26828, irregular (r=0.44): 53, irregular (r=0.96): 45, irregular (r=0.61): 46, irregular (r=0.51): 54, irregular (r=0.59): 51, irregular (r=0.49): 53, irregular (r=0.52): 54, irregular (r=0.57): 65, irregular (r=0.38): 24, irregular (r=0.34): 17, irregular (r=0.72): 47, irregular (r=0.63): 63, irregular (r=0.45): 43, irregular (r=0.98): 39, irregular (r=0.99): 29, irregular (r=0.39): 35, irregular (r=0.56): 75, irregular (r=0.37): 26, irregular (r=0.36): 26, irregular (r=0.47): 48, irregular (r=0.30): 25, irregular (r=0.46): 53, irregular (r=0.50): 74, irregular (r=0.55): 57, irregular (r=0.53): 70, irregular (r=0.35): 25, irregular (r=0.42): 34, irregular (r=0.43): 29, irregular (r=0.76): 69, irregular (r=0.62): 63, irregular (r=0.41): 27, irregular (r=0.48): 38, irregular (r=0.40): 42, irregular (r=0.64): 73, irregular (r=0.58): 63, irregular (r=0.31): 15, irregular (r=0.67): 49, irregular (r=0.70): 38, irregular (r=0.82): 94, irregular (r=0.65): 46, irregular (r=0.54): 63, irregular (r=0.80): 70, irregular (r=0.75): 72, irregular (r=0.66): 60, irregular (r=0.29): 21, irregular (r=0.89): 61, irregular (r=0.78): 71, irregular (r=0.79): 68, irregular (r=0.71): 43, irregular (r=0.77): 68, irregular (r=0.81): 75, irregular (r=0.74): 77, irregular (r=0.87): 63, irregular (r=0.69): 54, irregular (r=0.73): 61, irregular (r=0.88): 69, irregular (r=0.91): 57, irregular (r=1.00): 13, irregular (r=0.83): 63, irregular (r=0.94): 47, irregular (r=0.85): 63, irregular (r=0.92): 49, irregular (r=0.84): 64, irregular (r=0.95): 40, irregular (r=0.93): 51, irregular (r=0.60): 70, irregular (r=0.26): 16, irregular (r=0.86): 62, irregular (r=0.97): 34, irregular (r=0.33): 15, irregular (r=0.32): 18, irregular (r=0.90): 63, irregular (r=0.68): 56, irregular (r=0.27): 13, irregular (r=0.21): 2, irregular (r=0.28): 13, irregular (r=0.25): 9, irregular (r=0.22): 4, irregular (r=0.24): 2
- E: too few ACF zero crossings: 18184, irregular (r=0.65): 9, regular: 18823, irregular (r=0.70): 7, irregular (r=0.99): 15, irregular (r=0.75): 13, irregular (r=0.73): 8, irregular (r=0.77): 13, irregular (r=0.94): 20, irregular (r=0.88): 30, irregular (r=0.61): 15, irregular (r=0.60): 13, irregular (r=0.72): 7, irregular (r=0.74): 10, irregular (r=0.92): 21, irregular (r=0.98): 7, irregular (r=0.83): 20, irregular (r=0.97): 10, irregular (r=0.82): 13, irregular (r=0.89): 19, irregular (r=0.86): 16, irregular (r=0.80): 12, irregular (r=0.85): 25, irregular (r=0.78): 12, irregular (r=0.64): 10, irregular (r=0.95): 17, irregular (r=0.42): 11, irregular (r=0.63): 27, irregular (r=0.31): 8, irregular (r=0.33): 6, irregular (r=0.66): 8, irregular (r=0.55): 12, irregular (r=0.54): 13, irregular (r=0.84): 18, irregular (r=0.57): 11, irregular (r=0.56): 5, irregular (r=0.43): 8, irregular (r=0.93): 22, irregular (r=0.35): 10, irregular (r=0.51): 6, irregular (r=0.32): 4, irregular (r=0.87): 23, irregular (r=0.48): 7, irregular (r=0.81): 12, irregular (r=0.39): 8, irregular (r=0.45): 14, irregular (r=0.40): 9, irregular (r=0.62): 9, irregular (r=0.67): 12, irregular (r=0.76): 14, irregular (r=0.91): 9, irregular (r=0.50): 13, irregular (r=0.90): 21, irregular (r=0.96): 8, irregular (r=0.71): 6, irregular (r=0.36): 4, irregular (r=0.26): 1, irregular (r=0.41): 9, irregular (r=0.52): 8, irregular (r=0.46): 5, irregular (r=0.79): 16, irregular (r=0.47): 5, irregular (r=0.44): 8, irregular (r=0.34): 2, irregular (r=0.68): 11, irregular (r=1.00): 1, irregular (r=0.59): 11, irregular (r=0.69): 5, irregular (r=0.58): 7, irregular (r=0.49): 8, irregular (r=0.37): 3, irregular (r=0.53): 5, irregular (r=0.38): 4, irregular (r=0.28): 1, irregular (r=0.30): 2, irregular (r=0.29): 1

## Reason counts (negatives)

- A: too few ACF zero crossings: 1853, irregular (r=0.76): 6, irregular (r=0.83): 3, irregular (r=0.59): 6, irregular (r=0.39): 4, irregular (r=0.51): 13, regular: 19, irregular (r=0.84): 4, irregular (r=0.27): 1, irregular (r=0.66): 3, irregular (r=0.56): 7, irregular (r=0.48): 6, irregular (r=0.47): 4, irregular (r=0.58): 8, irregular (r=0.82): 5, irregular (r=0.52): 7, irregular (r=0.75): 3, irregular (r=0.32): 3, irregular (r=0.40): 10, irregular (r=0.44): 8, irregular (r=0.64): 4, irregular (r=0.26): 1, irregular (r=0.68): 2, irregular (r=0.62): 4, irregular (r=0.38): 3, irregular (r=0.60): 4, irregular (r=0.99): 1, irregular (r=0.41): 7, irregular (r=0.36): 5, irregular (r=0.53): 5, irregular (r=0.50): 10, irregular (r=0.91): 3, irregular (r=0.54): 3, irregular (r=0.96): 1, irregular (r=0.90): 1, irregular (r=0.86): 3, irregular (r=0.77): 2, irregular (r=0.55): 3, irregular (r=0.37): 2, irregular (r=0.43): 7, irregular (r=0.46): 3, irregular (r=0.65): 3, irregular (r=0.61): 5, irregular (r=0.33): 3, irregular (r=0.42): 2, irregular (r=0.49): 2, irregular (r=0.85): 1, irregular (r=0.25): 1, irregular (r=0.88): 4, irregular (r=0.81): 1, irregular (r=0.34): 2, irregular (r=0.78): 2, irregular (r=0.97): 1, irregular (r=0.63): 4, irregular (r=0.79): 2, irregular (r=0.74): 2, irregular (r=0.80): 3, irregular (r=0.72): 1, irregular (r=0.35): 2, irregular (r=0.69): 1, irregular (r=0.73): 2, irregular (r=1.00): 1, irregular (r=0.70): 2, irregular (r=0.45): 2, irregular (r=0.31): 1, irregular (r=0.67): 2, irregular (r=0.89): 1
- B: too few ACF zero crossings: 1339, regular: 203, irregular (r=0.54): 11, irregular (r=0.39): 7, irregular (r=0.55): 13, irregular (r=0.83): 6, irregular (r=0.59): 12, irregular (r=0.46): 7, irregular (r=0.51): 13, irregular (r=0.48): 13, irregular (r=0.75): 14, irregular (r=0.50): 12, irregular (r=0.84): 7, irregular (r=0.27): 2, irregular (r=0.73): 7, irregular (r=0.66): 10, irregular (r=0.64): 16, irregular (r=0.56): 12, irregular (r=0.47): 13, irregular (r=0.58): 11, irregular (r=0.82): 8, irregular (r=0.52): 15, irregular (r=0.32): 2, irregular (r=0.60): 21, irregular (r=0.40): 13, irregular (r=0.44): 9, irregular (r=0.68): 10, irregular (r=0.62): 14, irregular (r=0.38): 6, irregular (r=0.25): 2, irregular (r=0.95): 4, irregular (r=0.78): 8, irregular (r=0.99): 3, irregular (r=0.41): 9, irregular (r=0.36): 6, irregular (r=0.53): 15, irregular (r=0.91): 6, irregular (r=0.96): 4, irregular (r=0.76): 10, irregular (r=0.90): 3, irregular (r=0.86): 10, irregular (r=0.77): 12, irregular (r=0.37): 3, irregular (r=0.43): 5, irregular (r=0.65): 14, irregular (r=0.61): 9, irregular (r=0.33): 2, irregular (r=0.42): 3, irregular (r=0.49): 8, irregular (r=0.85): 7, irregular (r=0.88): 8, irregular (r=0.81): 6, irregular (r=0.34): 3, irregular (r=0.97): 3, irregular (r=0.63): 6, irregular (r=0.79): 14, irregular (r=0.74): 4, irregular (r=0.87): 7, irregular (r=0.93): 2, irregular (r=0.72): 6, irregular (r=0.94): 4, irregular (r=0.92): 6, irregular (r=0.71): 6, irregular (r=0.45): 6, irregular (r=0.98): 5, irregular (r=0.67): 10, irregular (r=0.89): 9, irregular (r=0.57): 6, irregular (r=1.00): 2, irregular (r=0.69): 10, irregular (r=0.80): 3, irregular (r=0.35): 1, irregular (r=0.70): 4
- C: too few ACF zero crossings: 1767, regular: 47, irregular (r=0.76): 6, irregular (r=0.39): 6, irregular (r=0.55): 5, irregular (r=0.83): 5, irregular (r=0.59): 7, irregular (r=0.50): 13, irregular (r=0.40): 8, irregular (r=0.51): 13, irregular (r=0.56): 7, irregular (r=0.75): 5, irregular (r=0.77): 5, irregular (r=0.27): 2, irregular (r=0.64): 7, irregular (r=0.66): 2, irregular (r=0.48): 7, irregular (r=0.47): 5, irregular (r=0.58): 8, irregular (r=0.89): 1, irregular (r=0.82): 5, irregular (r=0.52): 7, irregular (r=0.32): 3, irregular (r=0.78): 5, irregular (r=0.60): 6, irregular (r=0.42): 3, irregular (r=0.44): 8, irregular (r=0.46): 4, irregular (r=0.68): 4, irregular (r=0.37): 3, irregular (r=0.35): 4, irregular (r=0.62): 7, irregular (r=0.38): 3, irregular (r=0.25): 2, irregular (r=0.95): 2, irregular (r=0.41): 9, irregular (r=0.84): 2, irregular (r=0.99): 1, irregular (r=0.36): 8, irregular (r=0.71): 1, irregular (r=0.53): 4, irregular (r=0.91): 3, irregular (r=0.54): 5, irregular (r=0.96): 2, irregular (r=0.90): 2, irregular (r=0.86): 4, irregular (r=0.43): 6, irregular (r=0.65): 3, irregular (r=0.61): 6, irregular (r=0.33): 2, irregular (r=0.49): 2, irregular (r=0.85): 1, irregular (r=0.88): 4, irregular (r=0.81): 2, irregular (r=0.34): 3, irregular (r=0.97): 1, irregular (r=0.63): 6, irregular (r=0.79): 2, irregular (r=0.74): 2, irregular (r=0.57): 4, irregular (r=0.73): 5, irregular (r=0.45): 6, irregular (r=0.69): 2, irregular (r=0.80): 1, irregular (r=0.72): 1, irregular (r=1.00): 1, irregular (r=0.31): 3, irregular (r=0.70): 1, irregular (r=0.67): 2, irregular (r=0.87): 1
- D: irregular (r=0.58): 14, irregular (r=0.27): 3, irregular (r=0.32): 5, irregular (r=0.66): 13, irregular (r=1.00): 5, irregular (r=0.48): 16, irregular (r=0.57): 18, irregular (r=0.63): 15, irregular (r=0.69): 12, regular: 126, irregular (r=0.49): 11, irregular (r=0.52): 12, irregular (r=0.47): 17, irregular (r=0.41): 11, irregular (r=0.54): 14, irregular (r=0.51): 18, irregular (r=0.99): 4, irregular (r=0.34): 7, irregular (r=0.98): 3, irregular (r=0.72): 15, irregular (r=0.56): 12, irregular (r=0.55): 20, irregular (r=0.31): 3, irregular (r=0.61): 19, irregular (r=0.45): 21, irregular (r=0.38): 8, irregular (r=0.40): 9, irregular (r=0.42): 7, irregular (r=0.24): 2, irregular (r=0.80): 9, irregular (r=0.81): 11, irregular (r=0.70): 12, irregular (r=0.37): 9, irregular (r=0.35): 6, irregular (r=0.62): 7, irregular (r=0.64): 10, irregular (r=0.95): 4, irregular (r=0.26): 3, irregular (r=0.76): 9, irregular (r=0.33): 6, irregular (r=0.73): 9, irregular (r=0.68): 11, irregular (r=0.50): 19, irregular (r=0.59): 17, irregular (r=0.83): 5, irregular (r=0.36): 10, irregular (r=0.65): 17, irregular (r=0.60): 17, irregular (r=0.46): 14, irregular (r=0.84): 4, irregular (r=0.87): 3, irregular (r=0.29): 2, irregular (r=0.88): 4, irregular (r=0.53): 13, irregular (r=0.92): 5, irregular (r=0.77): 6, irregular (r=0.44): 10, irregular (r=0.82): 10, irregular (r=0.89): 3, irregular (r=0.43): 17, irregular (r=0.74): 12, irregular (r=0.85): 3, irregular (r=0.39): 11, irregular (r=0.71): 10, irregular (r=0.30): 3, irregular (r=0.86): 4, irregular (r=0.91): 5, irregular (r=0.25): 1, irregular (r=0.79): 6, irregular (r=0.94): 3, too few ACF zero crossings: 1292, irregular (r=0.97): 2, irregular (r=0.90): 4, irregular (r=0.67): 8, irregular (r=0.75): 7, irregular (r=0.93): 3, irregular (r=0.96): 3, irregular (r=0.78): 1
- E: too few ACF zero crossings: 1778, regular: 48, irregular (r=0.76): 7, irregular (r=0.39): 6, irregular (r=0.55): 5, irregular (r=0.83): 5, irregular (r=0.59): 7, irregular (r=0.46): 5, irregular (r=0.51): 14, irregular (r=0.48): 7, irregular (r=0.75): 5, irregular (r=0.50): 11, irregular (r=0.84): 4, irregular (r=0.27): 2, irregular (r=0.64): 6, irregular (r=0.66): 3, irregular (r=0.56): 7, irregular (r=0.47): 4, irregular (r=0.58): 9, irregular (r=0.82): 7, irregular (r=0.52): 7, irregular (r=0.32): 3, irregular (r=0.60): 6, irregular (r=0.40): 10, irregular (r=0.44): 8, irregular (r=0.26): 1, irregular (r=0.68): 3, irregular (r=0.62): 7, irregular (r=0.38): 3, irregular (r=0.25): 2, irregular (r=0.95): 2, irregular (r=0.78): 3, irregular (r=0.99): 1, irregular (r=0.41): 7, irregular (r=0.36): 7, irregular (r=0.53): 5, irregular (r=0.91): 3, irregular (r=0.54): 3, irregular (r=0.96): 2, irregular (r=0.90): 1, irregular (r=0.86): 4, irregular (r=0.77): 3, irregular (r=0.37): 2, irregular (r=0.43): 7, irregular (r=0.65): 4, irregular (r=0.61): 5, irregular (r=0.33): 3, irregular (r=0.42): 2, irregular (r=0.49): 3, irregular (r=0.85): 1, irregular (r=0.88): 4, irregular (r=0.81): 1, irregular (r=0.34): 2, irregular (r=0.97): 1, irregular (r=0.63): 4, irregular (r=0.79): 2, irregular (r=0.74): 2, irregular (r=0.57): 2, irregular (r=0.73): 5, irregular (r=0.69): 2, irregular (r=0.80): 3, irregular (r=0.72): 1, irregular (r=0.35): 2, irregular (r=1.00): 1, irregular (r=0.70): 2, irregular (r=0.45): 3, irregular (r=0.31): 2, irregular (r=0.67): 2, irregular (r=0.89): 1

## Per-cell detection share, negatives (percent)

| cell | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| neg white n=300 | 0 | 4 | 5 | 7 | 4 |
| neg white n=1000 | 3 | 14 | 11 | 9 | 12 |
| neg white n=3000 | 1 | 1 | 1 | 7 | 1 |
| neg ar050 n=300 | 0 | 13 | 0 | 17 | 0 |
| neg ar050 n=1000 | 4 | 19 | 14 | 8 | 14 |
| neg ar050 n=3000 | 11 | 20 | 12 | 16 | 13 |
| neg ar090 n=300 | 0 | 7 | 0 | 5 | 0 |
| neg ar090 n=1000 | 0 | 30 | 2 | 22 | 2 |
| neg ar090 n=3000 | 0 | 21 | 1 | 9 | 1 |
| neg ar097 n=300 | 0 | 2 | 0 | 1 | 0 |
| neg ar097 n=1000 | 0 | 20 | 0 | 3 | 0 |
| neg ar097 n=3000 | 0 | 26 | 0 | 17 | 0 |
| neg ar099 n=300 | 0 | 0 | 0 | 0 | 0 |
| neg ar099 n=1000 | 0 | 3 | 0 | 0 | 0 |
| neg ar099 n=3000 | 0 | 19 | 0 | 3 | 0 |
| neg random_walk n=300 | 0 | 0 | 0 | 1 | 0 |
| neg random_walk n=1000 | 0 | 0 | 0 | 0 | 0 |
| neg random_walk n=3000 | 0 | 3 | 0 | 1 | 0 |
| neg sp_steps n=300 | 0 | 0 | 0 | 0 | 0 |
| neg sp_steps n=1000 | 0 | 0 | 0 | 0 | 0 |
| neg sp_steps n=3000 | 0 | 1 | 1 | 0 | 1 |

## Per-cell detection share, positives (percent)

| cell | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| pos sine n=300 c=3 snr=2.0 white | 0 | 0 | 0 | 26 | 0 |
| pos sine n=300 c=3 snr=1.0 white | 0 | 0 | 0 | 36 | 0 |
| pos sine n=300 c=3 snr=0.5 white | 0 | 0 | 0 | 24 | 0 |
| pos sine n=300 c=4 snr=2.0 white | 0 | 1 | 3 | 100 | 0 |
| pos sine n=300 c=4 snr=1.0 white | 0 | 1 | 6 | 100 | 0 |
| pos sine n=300 c=4 snr=0.5 white | 0 | 0 | 1 | 47 | 0 |
| pos sine n=300 c=5 snr=2.0 white | 0 | 93 | 91 | 100 | 69 |
| pos sine n=300 c=5 snr=1.0 white | 0 | 87 | 83 | 100 | 61 |
| pos sine n=300 c=5 snr=0.5 white | 0 | 28 | 17 | 57 | 15 |
| pos sine n=300 c=6 snr=2.0 white | 1 | 100 | 99 | 100 | 99 |
| pos sine n=300 c=6 snr=1.0 white | 1 | 99 | 100 | 100 | 99 |
| pos sine n=300 c=6 snr=0.5 white | 0 | 61 | 45 | 66 | 43 |
| pos sine n=300 c=8 snr=2.0 white | 98 | 100 | 100 | 100 | 100 |
| pos sine n=300 c=8 snr=1.0 white | 94 | 100 | 98 | 100 | 99 |
| pos sine n=300 c=8 snr=0.5 white | 22 | 59 | 45 | 79 | 49 |
| pos sine n=300 c=10 snr=2.0 white | 100 | 100 | 99 | 100 | 100 |
| pos sine n=300 c=10 snr=1.0 white | 98 | 100 | 98 | 99 | 100 |
| pos sine n=300 c=10 snr=0.5 white | 35 | 56 | 47 | 73 | 49 |
| pos sine n=300 c=20 snr=2.0 white | 100 | 99 | 95 | 94 | 100 |
| pos sine n=300 c=20 snr=1.0 white | 94 | 94 | 93 | 94 | 95 |
| pos sine n=300 c=20 snr=0.5 white | 15 | 29 | 22 | 26 | 27 |
| pos sine n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 8 | 0 |
| pos sine n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 18 | 0 |
| pos sine n=1000 c=3 snr=0.5 white | 0 | 0 | 0 | 31 | 0 |
| pos sine n=1000 c=4 snr=2.0 white | 0 | 0 | 0 | 100 | 0 |
| pos sine n=1000 c=4 snr=1.0 white | 0 | 0 | 6 | 100 | 0 |
| pos sine n=1000 c=4 snr=0.5 white | 0 | 0 | 31 | 64 | 0 |
| pos sine n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 83 |
| pos sine n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 100 | 83 |
| pos sine n=1000 c=5 snr=0.5 white | 0 | 95 | 93 | 55 | 79 |
| pos sine n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=6 snr=0.5 white | 0 | 96 | 97 | 55 | 97 |
| pos sine n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=8 snr=1.0 white | 100 | 100 | 99 | 100 | 100 |
| pos sine n=1000 c=8 snr=0.5 white | 97 | 98 | 99 | 89 | 100 |
| pos sine n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=10 snr=0.5 white | 98 | 99 | 93 | 98 | 98 |
| pos sine n=1000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=20 snr=1.0 white | 100 | 99 | 98 | 99 | 100 |
| pos sine n=1000 c=20 snr=0.5 white | 91 | 92 | 88 | 95 | 91 |
| pos sine n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 2 | 0 |
| pos sine n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 3 | 0 |
| pos sine n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 19 | 0 |
| pos sine n=3000 c=4 snr=2.0 white | 0 | 0 | 0 | 100 | 0 |
| pos sine n=3000 c=4 snr=1.0 white | 0 | 0 | 1 | 100 | 0 |
| pos sine n=3000 c=4 snr=0.5 white | 0 | 0 | 66 | 92 | 0 |
| pos sine n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 96 |
| pos sine n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 100 | 99 |
| pos sine n=3000 c=5 snr=0.5 white | 0 | 97 | 100 | 88 | 99 |
| pos sine n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=0.5 white | 0 | 98 | 100 | 83 | 100 |
| pos sine n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=0.5 white | 100 | 96 | 100 | 94 | 100 |
| pos sine n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=0.5 white | 100 | 99 | 100 | 99 | 100 |
| pos sine n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=0.5 white | 100 | 98 | 100 | 98 | 100 |
| pos sine n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 27 | 0 |
| pos sine n=300 c=3 snr=1.0 ar09 | 0 | 1 | 0 | 11 | 0 |
| pos sine n=300 c=3 snr=0.5 ar09 | 0 | 5 | 0 | 4 | 0 |
| pos sine n=300 c=4 snr=2.0 ar09 | 0 | 2 | 0 | 92 | 0 |
| pos sine n=300 c=4 snr=1.0 ar09 | 0 | 3 | 0 | 21 | 0 |
| pos sine n=300 c=4 snr=0.5 ar09 | 0 | 7 | 0 | 8 | 0 |
| pos sine n=300 c=5 snr=2.0 ar09 | 0 | 90 | 8 | 97 | 8 |
| pos sine n=300 c=5 snr=1.0 ar09 | 0 | 50 | 0 | 24 | 0 |
| pos sine n=300 c=5 snr=0.5 ar09 | 0 | 13 | 0 | 6 | 0 |
| pos sine n=300 c=6 snr=2.0 ar09 | 0 | 100 | 57 | 97 | 57 |
| pos sine n=300 c=6 snr=1.0 ar09 | 0 | 59 | 7 | 31 | 7 |
| pos sine n=300 c=6 snr=0.5 ar09 | 0 | 19 | 1 | 9 | 1 |
| pos sine n=300 c=8 snr=2.0 ar09 | 64 | 100 | 86 | 93 | 88 |
| pos sine n=300 c=8 snr=1.0 ar09 | 0 | 61 | 6 | 18 | 6 |
| pos sine n=300 c=8 snr=0.5 ar09 | 0 | 13 | 0 | 6 | 0 |
| pos sine n=300 c=10 snr=2.0 ar09 | 82 | 100 | 89 | 95 | 92 |
| pos sine n=300 c=10 snr=1.0 ar09 | 4 | 54 | 10 | 27 | 10 |
| pos sine n=300 c=10 snr=0.5 ar09 | 0 | 15 | 0 | 7 | 0 |
| pos sine n=300 c=20 snr=2.0 ar09 | 96 | 96 | 95 | 87 | 96 |
| pos sine n=300 c=20 snr=1.0 ar09 | 4 | 30 | 12 | 16 | 12 |
| pos sine n=300 c=20 snr=0.5 ar09 | 0 | 12 | 0 | 11 | 0 |
| pos sine n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 17 | 0 |
| pos sine n=1000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 20 | 0 |
| pos sine n=1000 c=3 snr=0.5 ar09 | 0 | 13 | 0 | 18 | 0 |
| pos sine n=1000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 100 | 0 |
| pos sine n=1000 c=4 snr=1.0 ar09 | 0 | 1 | 0 | 78 | 0 |
| pos sine n=1000 c=4 snr=0.5 ar09 | 0 | 16 | 0 | 31 | 0 |
| pos sine n=1000 c=5 snr=2.0 ar09 | 0 | 100 | 51 | 100 | 39 |
| pos sine n=1000 c=5 snr=1.0 ar09 | 0 | 95 | 6 | 78 | 6 |
| pos sine n=1000 c=5 snr=0.5 ar09 | 0 | 52 | 0 | 28 | 0 |
| pos sine n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 94 | 100 | 94 |
| pos sine n=1000 c=6 snr=1.0 ar09 | 0 | 98 | 35 | 82 | 33 |
| pos sine n=1000 c=6 snr=0.5 ar09 | 0 | 71 | 2 | 25 | 2 |
| pos sine n=1000 c=8 snr=2.0 ar09 | 95 | 100 | 98 | 100 | 99 |
| pos sine n=1000 c=8 snr=1.0 ar09 | 24 | 100 | 44 | 70 | 46 |
| pos sine n=1000 c=8 snr=0.5 ar09 | 1 | 73 | 4 | 22 | 4 |
| pos sine n=1000 c=10 snr=2.0 ar09 | 97 | 100 | 98 | 100 | 98 |
| pos sine n=1000 c=10 snr=1.0 ar09 | 24 | 93 | 38 | 57 | 41 |
| pos sine n=1000 c=10 snr=0.5 ar09 | 2 | 56 | 8 | 20 | 8 |
| pos sine n=1000 c=20 snr=2.0 ar09 | 97 | 100 | 93 | 94 | 97 |
| pos sine n=1000 c=20 snr=1.0 ar09 | 23 | 82 | 34 | 25 | 37 |
| pos sine n=1000 c=20 snr=0.5 ar09 | 0 | 31 | 0 | 20 | 0 |
| pos sine n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 4 | 0 |
| pos sine n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 10 | 0 |
| pos sine n=3000 c=3 snr=0.5 ar09 | 0 | 3 | 0 | 21 | 0 |
| pos sine n=3000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 100 | 0 |
| pos sine n=3000 c=4 snr=1.0 ar09 | 0 | 0 | 1 | 100 | 0 |
| pos sine n=3000 c=4 snr=0.5 ar09 | 0 | 3 | 1 | 70 | 0 |
| pos sine n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 100 | 100 | 88 |
| pos sine n=3000 c=5 snr=1.0 ar09 | 0 | 98 | 61 | 100 | 47 |
| pos sine n=3000 c=5 snr=0.5 ar09 | 0 | 30 | 12 | 73 | 8 |
| pos sine n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=1.0 ar09 | 0 | 100 | 90 | 100 | 87 |
| pos sine n=3000 c=6 snr=0.5 ar09 | 0 | 34 | 26 | 68 | 26 |
| pos sine n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 ar09 | 94 | 100 | 98 | 100 | 99 |
| pos sine n=3000 c=8 snr=0.5 ar09 | 17 | 47 | 39 | 58 | 40 |
| pos sine n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 ar09 | 97 | 100 | 94 | 100 | 100 |
| pos sine n=3000 c=10 snr=0.5 ar09 | 21 | 54 | 32 | 58 | 33 |
| pos sine n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 ar09 | 92 | 100 | 92 | 99 | 92 |
| pos sine n=3000 c=20 snr=0.5 ar09 | 10 | 79 | 23 | 22 | 23 |
| pos square n=300 c=3 snr=2.0 white | 0 | 0 | 0 | 23 | 0 |
| pos square n=300 c=3 snr=1.0 white | 0 | 0 | 0 | 26 | 0 |
| pos square n=300 c=3 snr=0.5 white | 0 | 0 | 0 | 41 | 0 |
| pos square n=300 c=4 snr=2.0 white | 0 | 1 | 13 | 100 | 0 |
| pos square n=300 c=4 snr=1.0 white | 0 | 1 | 12 | 100 | 0 |
| pos square n=300 c=4 snr=0.5 white | 0 | 0 | 3 | 84 | 0 |
| pos square n=300 c=5 snr=2.0 white | 0 | 91 | 95 | 100 | 72 |
| pos square n=300 c=5 snr=1.0 white | 0 | 87 | 93 | 100 | 63 |
| pos square n=300 c=5 snr=0.5 white | 0 | 58 | 39 | 86 | 31 |
| pos square n=300 c=6 snr=2.0 white | 1 | 100 | 100 | 100 | 99 |
| pos square n=300 c=6 snr=1.0 white | 1 | 99 | 100 | 100 | 99 |
| pos square n=300 c=6 snr=0.5 white | 1 | 86 | 70 | 83 | 67 |
| pos square n=300 c=8 snr=2.0 white | 98 | 100 | 100 | 100 | 100 |
| pos square n=300 c=8 snr=1.0 white | 95 | 100 | 99 | 100 | 100 |
| pos square n=300 c=8 snr=0.5 white | 51 | 91 | 75 | 96 | 81 |
| pos square n=300 c=10 snr=2.0 white | 98 | 100 | 99 | 100 | 99 |
| pos square n=300 c=10 snr=1.0 white | 99 | 100 | 99 | 100 | 100 |
| pos square n=300 c=10 snr=0.5 white | 63 | 83 | 73 | 95 | 82 |
| pos square n=300 c=20 snr=2.0 white | 100 | 99 | 96 | 95 | 100 |
| pos square n=300 c=20 snr=1.0 white | 100 | 99 | 96 | 95 | 100 |
| pos square n=300 c=20 snr=0.5 white | 38 | 41 | 41 | 59 | 42 |
| pos square n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 11 | 0 |
| pos square n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 14 | 0 |
| pos square n=1000 c=3 snr=0.5 white | 0 | 0 | 0 | 32 | 0 |
| pos square n=1000 c=4 snr=2.0 white | 0 | 0 | 5 | 100 | 0 |
| pos square n=1000 c=4 snr=1.0 white | 0 | 0 | 16 | 100 | 0 |
| pos square n=1000 c=4 snr=0.5 white | 0 | 0 | 39 | 91 | 0 |
| pos square n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 81 |
| pos square n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 100 | 82 |
| pos square n=1000 c=5 snr=0.5 white | 0 | 97 | 100 | 95 | 81 |
| pos square n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=0.5 white | 0 | 99 | 100 | 89 | 100 |
| pos square n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=0.5 white | 99 | 100 | 99 | 100 | 100 |
| pos square n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=0.5 white | 100 | 99 | 100 | 100 | 100 |
| pos square n=1000 c=20 snr=2.0 white | 100 | 100 | 99 | 100 | 100 |
| pos square n=1000 c=20 snr=1.0 white | 100 | 100 | 99 | 99 | 100 |
| pos square n=1000 c=20 snr=0.5 white | 96 | 96 | 93 | 99 | 96 |
| pos square n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 2 | 0 |
| pos square n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 3 | 0 |
| pos square n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 15 | 0 |
| pos square n=3000 c=4 snr=2.0 white | 0 | 0 | 2 | 100 | 0 |
| pos square n=3000 c=4 snr=1.0 white | 0 | 0 | 11 | 100 | 0 |
| pos square n=3000 c=4 snr=0.5 white | 0 | 0 | 71 | 100 | 0 |
| pos square n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 93 |
| pos square n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 100 | 95 |
| pos square n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 100 | 97 |
| pos square n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 99 | 100 |
| pos square n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 21 | 0 |
| pos square n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 11 | 0 |
| pos square n=300 c=3 snr=0.5 ar09 | 0 | 3 | 0 | 4 | 0 |
| pos square n=300 c=4 snr=2.0 ar09 | 0 | 1 | 4 | 99 | 0 |
| pos square n=300 c=4 snr=1.0 ar09 | 0 | 2 | 0 | 46 | 0 |
| pos square n=300 c=4 snr=0.5 ar09 | 0 | 2 | 0 | 12 | 0 |
| pos square n=300 c=5 snr=2.0 ar09 | 0 | 90 | 59 | 100 | 48 |
| pos square n=300 c=5 snr=1.0 ar09 | 0 | 73 | 0 | 47 | 0 |
| pos square n=300 c=5 snr=0.5 ar09 | 0 | 17 | 0 | 7 | 0 |
| pos square n=300 c=6 snr=2.0 ar09 | 1 | 100 | 92 | 100 | 91 |
| pos square n=300 c=6 snr=1.0 ar09 | 0 | 91 | 14 | 58 | 13 |
| pos square n=300 c=6 snr=0.5 ar09 | 0 | 28 | 2 | 14 | 2 |
| pos square n=300 c=8 snr=2.0 ar09 | 86 | 100 | 97 | 100 | 99 |
| pos square n=300 c=8 snr=1.0 ar09 | 10 | 88 | 33 | 49 | 34 |
| pos square n=300 c=8 snr=0.5 ar09 | 0 | 21 | 0 | 10 | 0 |
| pos square n=300 c=10 snr=2.0 ar09 | 98 | 100 | 97 | 100 | 100 |
| pos square n=300 c=10 snr=1.0 ar09 | 21 | 83 | 34 | 42 | 39 |
| pos square n=300 c=10 snr=0.5 ar09 | 0 | 28 | 0 | 12 | 0 |
| pos square n=300 c=20 snr=2.0 ar09 | 100 | 96 | 96 | 89 | 100 |
| pos square n=300 c=20 snr=1.0 ar09 | 29 | 64 | 36 | 24 | 41 |
| pos square n=300 c=20 snr=0.5 ar09 | 0 | 17 | 0 | 13 | 0 |
| pos square n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 13 | 0 |
| pos square n=1000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 19 | 0 |
| pos square n=1000 c=3 snr=0.5 ar09 | 0 | 12 | 0 | 16 | 0 |
| pos square n=1000 c=4 snr=2.0 ar09 | 0 | 0 | 1 | 100 | 0 |
| pos square n=1000 c=4 snr=1.0 ar09 | 0 | 0 | 1 | 98 | 0 |
| pos square n=1000 c=4 snr=0.5 ar09 | 0 | 7 | 0 | 44 | 0 |
| pos square n=1000 c=5 snr=2.0 ar09 | 0 | 100 | 95 | 100 | 70 |
| pos square n=1000 c=5 snr=1.0 ar09 | 0 | 100 | 27 | 94 | 20 |
| pos square n=1000 c=5 snr=0.5 ar09 | 0 | 64 | 1 | 43 | 1 |
| pos square n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 99 | 100 | 99 |
| pos square n=1000 c=6 snr=1.0 ar09 | 0 | 100 | 72 | 95 | 71 |
| pos square n=1000 c=6 snr=0.5 ar09 | 0 | 82 | 6 | 49 | 6 |
| pos square n=1000 c=8 snr=2.0 ar09 | 98 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 ar09 | 61 | 100 | 73 | 92 | 74 |
| pos square n=1000 c=8 snr=0.5 ar09 | 1 | 80 | 10 | 34 | 10 |
| pos square n=1000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 ar09 | 68 | 100 | 70 | 88 | 77 |
| pos square n=1000 c=10 snr=0.5 ar09 | 4 | 67 | 11 | 23 | 11 |
| pos square n=1000 c=20 snr=2.0 ar09 | 100 | 100 | 96 | 96 | 100 |
| pos square n=1000 c=20 snr=1.0 ar09 | 64 | 94 | 67 | 77 | 71 |
| pos square n=1000 c=20 snr=0.5 ar09 | 3 | 30 | 5 | 17 | 6 |
| pos square n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 5 | 0 |
| pos square n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 8 | 0 |
| pos square n=3000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 24 | 0 |
| pos square n=3000 c=4 snr=2.0 ar09 | 0 | 0 | 3 | 100 | 0 |
| pos square n=3000 c=4 snr=1.0 ar09 | 0 | 0 | 9 | 100 | 0 |
| pos square n=3000 c=4 snr=0.5 ar09 | 0 | 0 | 2 | 81 | 0 |
| pos square n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 100 | 100 | 92 |
| pos square n=3000 c=5 snr=1.0 ar09 | 0 | 99 | 94 | 100 | 78 |
| pos square n=3000 c=5 snr=0.5 ar09 | 0 | 49 | 30 | 88 | 21 |
| pos square n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=1.0 ar09 | 0 | 100 | 99 | 100 | 100 |
| pos square n=3000 c=6 snr=0.5 ar09 | 0 | 54 | 52 | 87 | 51 |
| pos square n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 ar09 | 99 | 100 | 99 | 100 | 100 |
| pos square n=3000 c=8 snr=0.5 ar09 | 30 | 74 | 54 | 85 | 58 |
| pos square n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 ar09 | 100 | 100 | 98 | 100 | 100 |
| pos square n=3000 c=10 snr=0.5 ar09 | 48 | 79 | 52 | 83 | 60 |
| pos square n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 ar09 | 99 | 100 | 98 | 100 | 99 |
| pos square n=3000 c=20 snr=0.5 ar09 | 30 | 93 | 31 | 59 | 33 |
| pos lagged_square n=300 c=3 snr=2.0 white | 0 | 0 | 0 | 21 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 white | 0 | 0 | 0 | 23 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 white | 0 | 0 | 0 | 22 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 white | 0 | 1 | 3 | 100 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 white | 0 | 1 | 5 | 100 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 white | 0 | 0 | 2 | 49 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 white | 0 | 93 | 89 | 100 | 66 |
| pos lagged_square n=300 c=5 snr=1.0 white | 0 | 88 | 81 | 100 | 56 |
| pos lagged_square n=300 c=5 snr=0.5 white | 0 | 33 | 20 | 63 | 17 |
| pos lagged_square n=300 c=6 snr=2.0 white | 1 | 100 | 100 | 100 | 99 |
| pos lagged_square n=300 c=6 snr=1.0 white | 1 | 99 | 98 | 100 | 98 |
| pos lagged_square n=300 c=6 snr=0.5 white | 0 | 60 | 49 | 68 | 47 |
| pos lagged_square n=300 c=8 snr=2.0 white | 96 | 100 | 99 | 100 | 100 |
| pos lagged_square n=300 c=8 snr=1.0 white | 90 | 100 | 95 | 100 | 99 |
| pos lagged_square n=300 c=8 snr=0.5 white | 21 | 59 | 47 | 76 | 49 |
| pos lagged_square n=300 c=10 snr=2.0 white | 99 | 100 | 100 | 100 | 100 |
| pos lagged_square n=300 c=10 snr=1.0 white | 96 | 99 | 96 | 100 | 100 |
| pos lagged_square n=300 c=10 snr=0.5 white | 36 | 56 | 45 | 77 | 49 |
| pos lagged_square n=300 c=20 snr=2.0 white | 100 | 99 | 97 | 95 | 100 |
| pos lagged_square n=300 c=20 snr=1.0 white | 89 | 90 | 88 | 93 | 91 |
| pos lagged_square n=300 c=20 snr=0.5 white | 13 | 25 | 20 | 25 | 21 |
| pos lagged_square n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 8 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 15 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 white | 0 | 0 | 0 | 24 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 white | 0 | 0 | 0 | 100 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 white | 0 | 0 | 6 | 100 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 white | 0 | 0 | 37 | 61 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 83 |
| pos lagged_square n=1000 c=5 snr=1.0 white | 0 | 99 | 99 | 100 | 83 |
| pos lagged_square n=1000 c=5 snr=0.5 white | 0 | 95 | 96 | 59 | 74 |
| pos lagged_square n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=6 snr=0.5 white | 0 | 95 | 99 | 60 | 99 |
| pos lagged_square n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=0.5 white | 96 | 99 | 97 | 87 | 100 |
| pos lagged_square n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=0.5 white | 97 | 99 | 96 | 96 | 98 |
| pos lagged_square n=1000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=20 snr=0.5 white | 89 | 87 | 88 | 95 | 89 |
| pos lagged_square n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 3 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 5 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 25 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 white | 0 | 0 | 0 | 100 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 white | 0 | 0 | 0 | 100 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 white | 0 | 0 | 66 | 97 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 93 |
| pos lagged_square n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 100 | 96 |
| pos lagged_square n=3000 c=5 snr=0.5 white | 0 | 96 | 100 | 84 | 99 |
| pos lagged_square n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=0.5 white | 0 | 97 | 100 | 81 | 100 |
| pos lagged_square n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=0.5 white | 100 | 96 | 100 | 94 | 100 |
| pos lagged_square n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=0.5 white | 100 | 98 | 100 | 98 | 100 |
| pos lagged_square n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 15 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 ar09 | 0 | 1 | 0 | 5 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 ar09 | 0 | 5 | 0 | 3 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 ar09 | 0 | 2 | 0 | 90 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 ar09 | 0 | 1 | 0 | 23 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 ar09 | 0 | 5 | 0 | 5 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 ar09 | 0 | 91 | 10 | 95 | 7 |
| pos lagged_square n=300 c=5 snr=1.0 ar09 | 0 | 52 | 0 | 25 | 0 |
| pos lagged_square n=300 c=5 snr=0.5 ar09 | 0 | 14 | 0 | 5 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 ar09 | 1 | 99 | 61 | 97 | 60 |
| pos lagged_square n=300 c=6 snr=1.0 ar09 | 0 | 69 | 8 | 30 | 8 |
| pos lagged_square n=300 c=6 snr=0.5 ar09 | 0 | 20 | 1 | 11 | 1 |
| pos lagged_square n=300 c=8 snr=2.0 ar09 | 58 | 100 | 86 | 96 | 90 |
| pos lagged_square n=300 c=8 snr=1.0 ar09 | 0 | 69 | 7 | 21 | 7 |
| pos lagged_square n=300 c=8 snr=0.5 ar09 | 0 | 15 | 0 | 5 | 0 |
| pos lagged_square n=300 c=10 snr=2.0 ar09 | 81 | 100 | 90 | 94 | 94 |
| pos lagged_square n=300 c=10 snr=1.0 ar09 | 5 | 54 | 11 | 25 | 11 |
| pos lagged_square n=300 c=10 snr=0.5 ar09 | 0 | 17 | 0 | 9 | 0 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 94 | 95 | 91 | 85 | 95 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 3 | 25 | 10 | 14 | 10 |
| pos lagged_square n=300 c=20 snr=0.5 ar09 | 0 | 12 | 0 | 12 | 0 |
| pos lagged_square n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 14 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 16 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 ar09 | 0 | 20 | 0 | 17 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 100 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 ar09 | 0 | 0 | 0 | 79 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 ar09 | 0 | 15 | 0 | 36 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 ar09 | 0 | 100 | 58 | 100 | 45 |
| pos lagged_square n=1000 c=5 snr=1.0 ar09 | 0 | 93 | 7 | 81 | 4 |
| pos lagged_square n=1000 c=5 snr=0.5 ar09 | 0 | 54 | 1 | 38 | 1 |
| pos lagged_square n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 95 | 100 | 96 |
| pos lagged_square n=1000 c=6 snr=1.0 ar09 | 0 | 97 | 28 | 75 | 28 |
| pos lagged_square n=1000 c=6 snr=0.5 ar09 | 0 | 71 | 3 | 27 | 3 |
| pos lagged_square n=1000 c=8 snr=2.0 ar09 | 93 | 100 | 97 | 100 | 99 |
| pos lagged_square n=1000 c=8 snr=1.0 ar09 | 15 | 98 | 37 | 67 | 38 |
| pos lagged_square n=1000 c=8 snr=0.5 ar09 | 1 | 68 | 6 | 23 | 6 |
| pos lagged_square n=1000 c=10 snr=2.0 ar09 | 94 | 100 | 94 | 100 | 97 |
| pos lagged_square n=1000 c=10 snr=1.0 ar09 | 33 | 94 | 42 | 60 | 44 |
| pos lagged_square n=1000 c=10 snr=0.5 ar09 | 1 | 58 | 5 | 19 | 5 |
| pos lagged_square n=1000 c=20 snr=2.0 ar09 | 98 | 100 | 93 | 94 | 98 |
| pos lagged_square n=1000 c=20 snr=1.0 ar09 | 28 | 83 | 36 | 34 | 38 |
| pos lagged_square n=1000 c=20 snr=0.5 ar09 | 0 | 29 | 0 | 18 | 0 |
| pos lagged_square n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 4 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 15 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 ar09 | 0 | 1 | 0 | 21 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 100 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 ar09 | 0 | 0 | 1 | 100 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 ar09 | 0 | 4 | 0 | 68 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 99 | 100 | 87 |
| pos lagged_square n=3000 c=5 snr=1.0 ar09 | 0 | 98 | 66 | 100 | 55 |
| pos lagged_square n=3000 c=5 snr=0.5 ar09 | 0 | 32 | 11 | 69 | 8 |
| pos lagged_square n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=1.0 ar09 | 0 | 100 | 91 | 100 | 91 |
| pos lagged_square n=3000 c=6 snr=0.5 ar09 | 0 | 39 | 26 | 71 | 26 |
| pos lagged_square n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 ar09 | 92 | 100 | 96 | 100 | 99 |
| pos lagged_square n=3000 c=8 snr=0.5 ar09 | 18 | 42 | 37 | 54 | 37 |
| pos lagged_square n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 ar09 | 94 | 100 | 89 | 100 | 96 |
| pos lagged_square n=3000 c=10 snr=0.5 ar09 | 21 | 56 | 30 | 59 | 31 |
| pos lagged_square n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 ar09 | 94 | 100 | 94 | 99 | 94 |
| pos lagged_square n=3000 c=20 snr=0.5 ar09 | 9 | 81 | 18 | 27 | 19 |
