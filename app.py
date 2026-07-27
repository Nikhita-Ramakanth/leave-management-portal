from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")
@app.route("/apply", methods=["GET", "POST"])
def apply():
    if request.method == "POST":
        name = request.form["name"]
        leave_type = request.form["leave_type"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        reason = request.form["reason"]

        return f"""
        <h2>Leave Request Submitted!</h2>
        <p><b>Name:</b> {name}</p>
        <p><b>Leave Type:</b> {leave_type}</p>
        <p><b>From:</b> {start_date} <b>To:</b> {end_date}</p>
        <p><b>Reason:</b> {reason}</p>
        <a href="/">Back to Home</a>
        """
    return render_template("apply.html")

if __name__ == "__main__":
    app.run(debug=True)