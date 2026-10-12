from docparse_service.config import Settings


def test_default_mineru_extra_args_force_pipeline():
    s = Settings()
    assert "-b pipeline" in s.mineru_cpu_extra_args or "--backend pipeline" in s.mineru_cpu_extra_args
    assert "--device cpu" in s.mineru_cpu_extra_args or "-d cpu" in s.mineru_cpu_extra_args
    assert "--device npu" in s.mineru_npu_extra_args or "-d npu" in s.mineru_npu_extra_args
