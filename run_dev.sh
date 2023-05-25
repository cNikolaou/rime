#!/bin/bash

set -e

PYTHON=${PYTHON:-python3.10}

# Parse command line arguments.
NO_AI=0
DEPS_ONLY=0
VITE_OPTS=
FLASK_OPTS=

while [[ $# -gt 0 ]]; do
	key="$1"
	case $key in
		--no-ai)
			NO_AI=1
			shift
			;;
		--deps-only)
			# Install dependencies and exit. Used by the Dockerfile to create a suitable image.
			DEPS_ONLY=1
			shift
			;;
		--host)
			VITE_OPTS="$VITE_OPTS --host"
			FLASK_OPTS="$FLASK_OPTS --host 0.0.0.0"
			shift
			;;
		*)
		echo "Unknown argument: $key"
			exit 1
		;;
	esac
done

# Create a virtualenv, install dependencies, and run the dev server.
if [ ! -f .venv/bin/activate ]; then
	echo Creating a virtualenv and installing dependencies.
	$PYTHON -m venv .venv
	source .venv/bin/activate
	pip install -r requirements.txt

	# Install AI requirements unless explicitly asked not to.
	if [ $NO_AI -eq 0 ]; then
		pip install -r rime/plugins/ai_requirements.txt
	fi
	echo Virtualenv created. To re-create this environment, delete .venv.
else
	source .venv/bin/activate
fi

cd frontend

# Always npm install because it doesn't take long.
npm install

# Exit if we only want to install dependencies.
if [ $DEPS_ONLY -eq 1 ]; then
	exit 0
fi

# Start Vite in the background. It will be killed when the script exits.
npm run dev -- $VITE_OPTS &
VITE_PID=$!

# Start Flask in the foreground.
flask --app rimeserver --debug run $FLASK_OPTS

