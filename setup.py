from setuptools import setup

setup(
    name="pdf_compressor",    
    version="1.0.0",               
    author="0213AN",
    py_modules=["pdf_compressor"], # 原始碼檔名
    install_requires=[             # 自動幫別人裝的套件清單
        "pymupdf",
        "Pillow",
    ],
    entry_points={
        'console_scripts': [
            'run_compressor = pdf_compressor:main',  #run的觸發詞
        ],
    },
)
