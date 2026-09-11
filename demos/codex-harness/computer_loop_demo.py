class FakeApp:
    def __init__(self):
        self.state = {"filters_open": False, "query": ""}

    def observe(self):
        return dict(self.state)

    def act(self, action):
        if action == "open_filters":
            self.state["filters_open"] = True
        elif action == "type_penguin" and self.state["filters_open"]:
            self.state["query"] = "penguin"
        else:
            raise ValueError("action not valid in current state")

app = FakeApp()
for step in range(5):
    observation = app.observe()
    if observation["filters_open"] and observation["query"] == "penguin":
        print("verified:", observation)
        break
    action = "open_filters" if not observation["filters_open"] else "type_penguin"
    app.act(action)
else:
    raise RuntimeError("task not completed within action budget")
assert app.observe() == {"filters_open": True, "query": "penguin"}
