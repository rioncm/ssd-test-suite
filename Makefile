.PHONY: test demo

test:
	python3 -m unittest discover -s tests -v

demo:
	python3 examples/make_demo.py /tmp/ssdbench-demo
