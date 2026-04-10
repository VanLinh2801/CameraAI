# PeopleNet model artifacts

Mount or copy your DeepStream-compatible PeopleNet files into this directory before starting
the `deepstream` service.

Supported layouts:

- `model.engine`
- `model.etlt` and `int8-calib.bin`
- `model.etlt` and `labels.txt` for FP32 fallback without calibration cache

If you use TAO `.etlt`, the startup flow assumes the default key `tlt_encode`.
